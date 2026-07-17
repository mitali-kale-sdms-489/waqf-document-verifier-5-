"""
Tesseract adapter — the always-available, offline OCR fallback (and the
Week 9 CER-benchmark baseline per the project doc). Requires the system
`tesseract` binary plus the `urd`, `mar`, and `eng` traineddata files; if any
is missing this degrades gracefully rather than crashing the pipeline.

Also does script detection (Urdu Nastaliq vs. Marathi/Hindi/Sanskrit
Devanagari vs. English/Latin) by counting Unicode code points per script
block in whatever raw text we've been able to read so far — used to pick
the right language hint for Sarvam Vision and the right `scriptType` on
the document, independent of whether Tesseract's own read quality is good
enough to use as the primary text.

Marathi, Hindi, and Sanskrit all share the Devanagari Unicode block, so
code-point counting alone can't tell them apart. `_classify_devanagari`
does a second pass over the same text once Devanagari is the winning
block, scoring it against small per-language function-word lexicons
(postpositions, copulas, conjunctions) that are genuinely distinctive
across the three languages. This is a heuristic, not a language-ID model —
short or copula-free text (e.g. a lone property ID or a name) can come
back with a zero-zero-zero score, in which case Hindi is used as the
default (matching Sarvam Vision's own hi-IN default for the block).
"""
from __future__ import annotations

import io
import logging
import re

from PIL import Image

from app.models import ExtractionSource, ScriptType
from .base import RawTextResult

logger = logging.getLogger(__name__)

DEVANAGARI_RANGE = (0x0900, 0x097F)
ARABIC_RANGES = [(0x0600, 0x06FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]

# Function words/suffixes that reliably distinguish the three Devanagari
# languages in scope. Kept short and high-precision rather than exhaustive:
# these are words that essentially never appear in the *other* two
# languages, so a single hit is decent evidence.
#
# The Sanskrit list was previously too short to reliably fire on real scans:
# short/terse administrative text (a name, a survey number, a single line of
# boilerplate) routinely produced a zero-zero-zero score across all three
# lexicons, which silently fell through to the Hindi default further down
# the pipeline (see pipeline.py:_final_script) — visible to users as
# "Sanskrit document uploaded, shows as Hindi". Broadened the Sanskrit list
# with common Waqf/legal-deed vocabulary (dāna/grant, sākṣī/witness,
# tasmāt/therefore, etc.) so it has a realistic chance of matching the kind
# of short, formal text these scans actually contain.
MARATHI_MARKERS = ["आहे", "आहेत", "मध्ये", "यांनी", "झाले", "केले", "आणि", "साठी", "चा ", "ची ", "चे "]
HINDI_MARKERS = ["है", "हैं", "में", "और", "किया", "हुआ", "के लिए", "का ", "की ", "के "]
SANSKRIT_MARKERS = [
    "अस्ति", "तस्य", "तस्याः", "इति", "एव", "स्वयं", "यत्र", "तत्र", "अथ", "स्य ", "स्याः",
    "तस्मात्", "तस्मिन्", "यस्य", "यस्याः", "कस्यचित्", "सर्वेषाम्", "एतत्", "एतस्य", "अपि",
    "साक्षी", "साक्षिणः", "दानम्", "दत्तम्", "समर्पितम्", "धर्मार्थम्", "निमित्तम्",
    "इत्यादि", "उक्तम्", "प्रमाणम्", "पूर्वकम्", "अनुसारेण", "सम्पत्तिः", "भूमिः", "ग्रामः",
]

# The avagraha (ऽ, U+093D) marks elided "a" in Sanskrit sandhi (e.g.
# "सोऽहम्") and is essentially never used in ordinary Hindi or Marathi prose.
# A single occurrence is strong, near-unique evidence for Sanskrit — used as
# a tie-breaker/booster in `_classify_devanagari` below, independent of the
# function-word lexicons (which can legitimately score zero on short,
# copula-free administrative text even when the avagraha is present).
AVAGRAHA = "\u093D"

# Words ending in visarga (ः) are common in Sanskrit nominal/adjectival
# endings (e.g. "देवः", "साक्षिणः") and comparatively rare in running
# Hindi/Marathi text, where visarga mostly survives only in borrowed
# Sanskrit words. A high density of visarga-final "words" (tokens split on
# whitespace/punctuation) is a secondary, weaker signal than the avagraha
# but still useful when the lexicon match is empty.
VISARGA = "\u0903"


def detect_script_from_filename(filename: str) -> ScriptType | None:
    """Weak last-resort signal: some scans are named with a script/language
    hint (e.g. 'WQ-UR-012.pdf' for Urdu). Only used as a tiebreaker when no
    OCR engine produced enough text to detect the script directly."""
    name = (filename or "").lower()
    if re.search(r"(?<![a-z])(ur|urdu)(?![a-z])", name):
        return ScriptType.urdu_nastaliq
    # Check the longer/more specific "mar"/"marathi" before the two-letter
    # "hi" code, since "mar" would otherwise never collide but "hin"/"hi"
    # and "san"/"sa" could both plausibly appear inside other words.
    if re.search(r"(?<![a-z])(mr|mar|marathi)(?![a-z])", name):
        return ScriptType.marathi_devanagari
    if re.search(r"(?<![a-z])(sa|san|sanskrit)(?![a-z])", name):
        return ScriptType.sanskrit_devanagari
    if re.search(r"(?<![a-z])(hi|hin|hindi)(?![a-z])", name):
        return ScriptType.hindi_devanagari
    if re.search(r"(?<![a-z])(en|eng|english)(?![a-z])", name):
        return ScriptType.english_latin
    return None


# A lexicon "win" only overrides a same-family hint (filename- or
# early-OCR-derived) if it beats the hint's own score by more than this
# margin. Real Marathi administrative/registry text (names, survey
# numbers, boilerplate) routinely scores 0 against MARATHI_MARKERS while a
# single incidental or loanword hit (e.g. "में"/"और" appearing once) is
# enough to make Hindi "win" outright under a plain max(). That let one
# stray match silently overrule a filename that explicitly said
# "marathi" — this margin means a hint is only overridden by genuinely
# decisive evidence, not a single stray word.
DEVANAGARI_OVERRIDE_MARGIN = 2


def _classify_devanagari(text: str, hint: ScriptType | None = None) -> ScriptType | None:
    """Scores Devanagari text against Marathi/Hindi/Sanskrit function-word
    lexicons and returns the best match. Returns None on a zero-evidence
    score (e.g. a single name or property ID with no function words) so the
    caller can fall back to a filename hint or another signal instead of
    this heuristic silently guessing Hindi — that guess was overriding
    correct filename-based hints for Sanskrit/Marathi scans whenever the OCR
    text was too short to carry any distinguishing marker word.

    `hint` (typically the filename-derived script, or an early OCR pass'
    guess) is a Devanagari sub-type this text is already believed to be.
    When the lexicon "winner" only barely edges out the hint's own score
    (see DEVANAGARI_OVERRIDE_MARGIN) — rather than clearly beating it — the
    hint is kept instead of flipping on what's likely just an incidental
    word match. A hint is only overridden when the evidence for a
    different script is decisively stronger.

    Before falling back to "no evidence", this also checks for the
    avagraha (ऽ) and visarga (ः) — see the module-level comments on
    AVAGRAHA/VISARGA. Real Sanskrit scans are often short, formal lines
    (a name, a grant clause, a witness line) that don't happen to contain
    any of the SANSKRIT_MARKERS function words but still carry these
    script-level tells, which is what was causing genuine Sanskrit scans to
    silently fall through to the Hindi default."""
    scores = {
        ScriptType.marathi_devanagari: sum(text.count(m) for m in MARATHI_MARKERS),
        ScriptType.hindi_devanagari: sum(text.count(m) for m in HINDI_MARKERS),
        ScriptType.sanskrit_devanagari: sum(text.count(m) for m in SANSKRIT_MARKERS),
    }
    best_script, best_score = max(scores.items(), key=lambda kv: kv[1])

    if best_score > 0:
        if (
            hint in scores
            and hint != best_script
            and (best_score - scores[hint]) <= DEVANAGARI_OVERRIDE_MARGIN
        ):
            return hint
        return best_script

    # No function-word evidence at all — try the weaker, script-level
    # Sanskrit signals before giving up.
    if AVAGRAHA in text:
        return ScriptType.sanskrit_devanagari

    words = re.split(r"[\s।॥,.;:()\-]+", text)
    words = [w for w in words if w]
    if words:
        visarga_ratio = sum(1 for w in words if w.endswith(VISARGA)) / len(words)
        if visarga_ratio >= 0.15:
            return ScriptType.sanskrit_devanagari

    return hint


def detect_script(
    text: str, min_evidence: int = 1, hint: ScriptType | None = None
) -> ScriptType | None:
    """Returns None when there isn't enough signal (e.g. empty/garbled
    text, or fewer than `min_evidence` matching characters) so the caller
    can fall back to a default instead of trusting a low-evidence guess.

    Counts evidence for the Devanagari block, the Arabic block, and Latin
    letters and picks whichever has the most; a Devanagari win is then
    disambiguated into Marathi/Hindi/Sanskrit via `_classify_devanagari`.
    Previously this only weighed Devanagari vs. Arabic, so a plain-Latin/
    English document (zero of either) fell through to a default that could
    land on Urdu, which is what was mislabeling English scans.

    `hint`, when given a Devanagari sub-type (Marathi/Hindi/Sanskrit) —
    typically the filename-derived script — is forwarded to
    `_classify_devanagari` so a marginal/incidental lexicon match doesn't
    silently overrule it (see DEVANAGARI_OVERRIDE_MARGIN there). This is
    what fixes filenames like `..._marathi_....pdf` being reported as
    Hindi: short administrative Marathi text often has zero Marathi
    function-word matches, and a single incidental Hindi word was enough
    to win outright before this hint was threaded through.

    `min_evidence` defaults to 1 (any signal at all) for callers
    re-detecting from a winning engine's full transcription, where a
    single matching character is already reasonably meaningful. Callers
    using this on a noisy, low-quality quick-pass OCR read purely as a
    *hint* for another engine's language parameter should pass a higher
    threshold — a single misread/garbled character from a low-confidence
    Tesseract pass was, before this, enough to send e.g. Sarvam Vision an
    Urdu language hint for what was actually a Sanskrit/Devanagari scan,
    which then produces fluent-looking Nastaliq text for name/place
    fields (see pipeline.py's early_hint usage and the corresponding
    foreign-script guard in base.py/qwen_mapper.py)."""
    if not text:
        return None

    devanagari = sum(1 for ch in text if DEVANAGARI_RANGE[0] <= ord(ch) <= DEVANAGARI_RANGE[1])
    arabic = sum(
        1
        for ch in text
        if any(lo <= ord(ch) <= hi for lo, hi in ARABIC_RANGES)
    )
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())

    counts = {
        "devanagari": devanagari,
        ScriptType.urdu_nastaliq: arabic,
        ScriptType.english_latin: latin,
    }
    best_key, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count < min_evidence:
        return None
    if best_key == "devanagari":
        return _classify_devanagari(text, hint)
    return best_key


def _load_image(raw_bytes: bytes, mime_type: str | None) -> Image.Image | None:
    if mime_type == "application/pdf" or (raw_bytes[:4] == b"%PDF"):
        try:
            import fitz  # PyMuPDF — optional dependency, first page only

            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            pix = doc[0].get_pixmap(dpi=300)
            return Image.open(io.BytesIO(pix.tobytes("png")))
        except Exception:
            logger.info("PDF rasterization unavailable (PyMuPDF not installed or failed); "
                        "skipping Tesseract pass for this file.")
            return None

    try:
        return Image.open(io.BytesIO(raw_bytes))
    except Exception:
        return None


def run_tesseract(raw_bytes: bytes, mime_type: str | None) -> RawTextResult:
    try:
        import pytesseract
    except ImportError:
        return RawTextResult(text="", engine=ExtractionSource.tesseract, confidence=0.0,
                              error="pytesseract not installed")

    image = _load_image(raw_bytes, mime_type)
    if image is None:
        return RawTextResult(text="", engine=ExtractionSource.tesseract, confidence=0.0,
                              error="could not decode image for OCR")

    # eng/urd/mar were the original three; hin (Hindi) and san (Sanskrit)
    # are added for the same five scripts Sarvam Vision and the field
    # extraction stub now cover. If the hin/san traineddata files aren't
    # installed, Tesseract raises and we retry with just the original three
    # rather than losing this offline pass/script-hint entirely — see the
    # README for `apt install tesseract-ocr-hin tesseract-ocr-san`.
    lang_full = "eng+urd+mar+hin+san"
    lang_fallback = "eng+urd+mar"
    lang_used = lang_full
    try:
        text = pytesseract.image_to_string(image, lang=lang_full)
    except pytesseract.TesseractNotFoundError:
        return RawTextResult(text="", engine=ExtractionSource.tesseract, confidence=0.0,
                              error="tesseract binary not found on PATH")
    except Exception:
        try:
            text = pytesseract.image_to_string(image, lang=lang_fallback)
            lang_used = lang_fallback
        except Exception as exc:  # missing urd/mar/eng traineddata, corrupt image, etc.
            logger.warning("Tesseract OCR failed: %s", exc)
            return RawTextResult(text="", engine=ExtractionSource.tesseract, confidence=0.0, error=str(exc))

    confidence = 0.0
    try:
        data = pytesseract.image_to_data(image, lang=lang_used, output_type=pytesseract.Output.DICT)
        word_confs = [int(c) for c in data.get("conf", []) if c not in ("-1", -1)]
        if word_confs:
            confidence = max(0.0, min(1.0, (sum(word_confs) / len(word_confs)) / 100))
    except Exception:
        # Confidence is a nice-to-have; a failed image_to_data call
        # shouldn't discard a successful image_to_string read.
        confidence = 0.5 if text.strip() else 0.0

    return RawTextResult(text=text.strip(), engine=ExtractionSource.tesseract, confidence=confidence)
