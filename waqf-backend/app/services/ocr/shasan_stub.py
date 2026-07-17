"""
Shasan-SLM extraction-assist stub.

Per the project doc's stack line ("Shasan-SLM API (Pod B) for extraction
assist") and the handoff note ("+ stubbed shasan slm"), Pod B's real
extraction-assist API doesn't exist yet. This module stands in for it: a
local, regex/heuristic field parser that runs against whatever raw OCR text
the primary engine (Sarvam Vision or Tesseract) produced, and returns field
readings tagged `source=shasan_slm` so the rest of the pipeline — and the
frontend, which already renders a "shasan_slm" badge — doesn't need to
change when the real API lands. Swapping this out for a real HTTP call to
`settings.shasan_slm_api_url` later is a one-file change (see run() below).

Field patterns are tuned to the record shapes shown in the project's own
synthetic sample set (data/mockDocuments.ts on the frontend), e.g.
"WQ/MH/2024/00812", survey numbers like "412/2-A", extents like "0.82 ha",
broadened with Hindi- and Sanskrit-language label keywords and Devanagari
numeral support alongside the original Urdu/Marathi/English coverage.

Confidence design: a field gets its base confidence from *how* it was
found (a strict format-regex match like the property-ID pattern is more
reliable than a loose "text after a label" match), then gets boosted if a
*second*, independent signal — the field's label keyword appearing
anywhere else in the document — agrees with it. That agreement between two
different extraction strategies is real corroborating evidence, not an
arbitrary confidence bump; see `_confidence` below.
"""
from __future__ import annotations

import re

from app.models import ExtractionSource, FieldName
from .base import FieldReading, FieldReadings

# Devanagari digits (०-९) map 1:1 to ASCII 0-9; several of the source
# languages here (Hindi, Marathi, Sanskrit) can render numerals natively.
# Normalizing up front means every numeric regex below only needs to
# handle ASCII digits once, for all three Devanagari languages plus Urdu
# (Urdu digits ۰-۹ are handled the same way).
_DIGIT_MAP = str.maketrans(
    "०१२३४५६७८९" "۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


def _normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


# Devanagari's short-i matra (ि, written *before* its consonant) and long-ii
# matra (ी, written *after* it) are one of the most commonly confused/
# interchanged vowel signs in both OCR output and hand-typed government
# records — e.g. a real scan had the label "मुतवल्लि-नाम" where
# LABEL_KEYWORDS only listed "मुतवल्ली", so the label-match silently missed
# and the field fell back to "not extracted". Folding one onto the other
# before comparing (label search only — not the digit/value regexes, where
# this substitution has no relevance) closes that whole class of miss
# without having to enumerate every spelling variant by hand. This is a
# 1:1 character substitution so string length/offsets are preserved.
_MATRA_EQUIV_MAP = str.maketrans({"\u093F": "\u0940"})  # ि -> ी


def _normalize_matra(text: str) -> str:
    return text.translate(_MATRA_EQUIV_MAP)


PROPERTY_ID_RE = re.compile(r"\b[A-Z]{2,5}[/\-][A-Z]{2}[/\-]\d{4}[/\-]\d{3,6}\b")
SURVEY_NUMBER_RE = re.compile(r"\b\d{1,4}\/\d{1,3}(?:-[A-Za-z\u0900-\u097F\u0600-\u06FF]+)?\b")
EXTENT_UNITS = (
    r"ha|hectares?|acres?|sq\.?\s?ft|"
    r"गुंठे|एकर|"          # Marathi
    r"हेक्टेयर|एकड़|वर्गफुट|बीघा|"  # Hindi
    r"हेक्टरम्|क्षेत्रम्"      # Sanskrit (approximate/administrative usage)
)
EXTENT_RE = re.compile(
    rf"\b\d{{1,3}}(?:\.\d{{1,2}})?\s?(?:{EXTENT_UNITS})(?:म्|ः|ं)?(?![\u0900-\u097F])",
    re.IGNORECASE,
)
DATE_PATTERNS = [
    re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b"),  # YYYY-MM-DD
    re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"),  # DD-MM-YYYY
]

# Label keywords per field, per script. English transliteration is
# included throughout too, since some scans mix scripts or are typed forms
# rather than handwritten. Where Hindi and Marathi legitimately share a
# spelling (e.g. "गांव"/village), the word is listed once rather than
# duplicated — duplicate keywords don't add matching power, only per-script
# variants that differ in spelling do.
LABEL_KEYWORDS: dict[FieldName, list[str]] = {
    FieldName.mutawalli_name: [
        # Checked in order, and the loop below returns on the first keyword
        # that matches a line — so the compound "Mutawalli Name" phrasings
        # real registers actually use are listed before the bare root.
        # Matching only the bare root first would still "work" (the root is
        # a substring of every compound form) but would leave the trailing
        # "नाम"/"name" word glued onto the front of the extracted value.
        "मुतवल्ली-नाम", "मुतवल्ली नाम", "मुतवल्लीचे नाव", "मुतवल्ली का नाम",
        "متولی", "mutawalli",
        "मुतवल्ली",  # shared Hindi/Marathi spelling — bare-root fallback
    ],
    FieldName.village: [
        "گاؤں", "village",
        "गाव", "गांव", "गाँव",  # Marathi / Hindi variants
        "मौजे", "ग्राम", "ग्रामः",  # Marathi "mauje" / Hindi-Sanskrit "gram"
    ],
    FieldName.property_id: [
        "جائیداد نمبر", "property id", "property no",
        "मालमत्ता",                        # Marathi
        "संपत्ति क्रमांक", "सम्पत्ति संख्या",  # Hindi
    ],
    FieldName.survey_number: [
        "سروے نمبر", "survey no", "survey number",
        "सर्वे क्रमांक",              # Marathi
        "सर्वेक्षण क्रमांक", "सर्वे नंबर",  # Hindi
    ],
    FieldName.registration_date: [
        "تاریخ اندراج", "registration date",
        "नोंदणी तारीख",              # Marathi
        "पंजीकरण तिथि", "पंजीकरण दिनांक",  # Hindi
        "दिनांक",                    # generic Hindi/Marathi/Sanskrit-adjacent "date"
    ],
    FieldName.extent: [
        "رقبہ", "extent",
        "क्षेत्रफळ",   # Marathi
        "क्षेत्रफल",   # Hindi
        "क्षेत्रफलम्",  # Sanskrit
    ],
}


def _find_label_value(text: str, keywords: list[str]) -> str | None:
    """Looks for 'Label: value' or 'Label value' on a single line and
    returns the trailing text, trimmed of separator punctuation. Falls back
    to the next non-empty line when the label has nothing trailing it on
    its own line — common in scanned forms where the label sits alone and
    the handwritten/typed value is on the line directly below it.

    Before extracting the "rest" of the line, the match is extended through
    a short run of Devanagari characters directly glued onto the keyword
    with no separator — this handles Sanskrit case-ending variants of a
    label (e.g. keyword "ग्राम" matching inside the label "ग्रामः", or
    "क्षेत्रफल" inside "क्षेत्रफलम्") where the keyword list only has the
    shorter Hindi/Marathi form.

    This extension is deliberately bounded to MAX_SUFFIX_EXTEND characters
    and stops dead at the first Devanagari digit. An earlier, unbounded
    version of this loop kept extending through *any* run of Devanagari
    characters — which includes Devanagari digits and vowel signs, not just
    case-ending consonants/virama/visarga/anusvara. On scans where the
    label's case-ending is glued directly onto the value with no space
    (e.g. a table cell OCR'd as "क्षेत्रफलम्१.२४हेक्टर१२गुंठे"), that let the
    "suffix" match run straight into the value and swallow most or all of
    it, leaving only its last glyph or two as the "rest" — which is what a
    single stray character like "म्" or "ः" showing up as a field's value
    actually was: not a missing-field case, but the real value being eaten
    by this loop. `_looks_like_junk` below is a second line of defense: even
    within the bounded extension, if what's left over is just combining
    marks/punctuation with no letter or digit, treat it as no match instead
    of returning garbage.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        normalized_line = _normalize_matra(line.lower())
        for kw in keywords:
            idx = normalized_line.find(_normalize_matra(kw.lower()))
            if idx == -1:
                continue
            end = idx + len(kw)
            end = _extend_over_case_suffix(line, end)
            rest = line[end:].strip(" :：\u060c-|\t").strip()
            if rest and not rest.startswith("_") and not _looks_like_junk(rest):
                return rest[:120].strip(" :：\u060c-|\t")
            # Label matched but nothing usable trails it on this line —
            # check the next non-empty line for a standalone value.
            for next_line in lines[i + 1 : i + 3]:
                candidate = next_line.strip(" :：\u060c-|\t")
                if (
                    candidate
                    and not _looks_like_junk(candidate)
                    and not any(k.lower() in candidate.lower() for k in keywords)
                ):
                    return candidate[:120].strip(" :：\u060c-|\t")
    return None


# Real Sanskrit case-ending suffixes glued onto a label are short: a
# standalone visarga/anusvara (ः/ं), or a consonant + virama (e.g. the "म्"
# in "फलम्", the "त्" in "त्" combinations). Two characters comfortably
# covers every case in the LABEL_KEYWORDS lists below; anything longer is
# almost certainly the start of the actual value, not a suffix, and should
# not be consumed.
MAX_SUFFIX_EXTEND = 2
_DEVANAGARI_DIGITS = range(0x0966, 0x0970)


def _extend_over_case_suffix(line: str, end: int) -> int:
    """Advances `end` past at most MAX_SUFFIX_EXTEND further Devanagari
    characters, stopping immediately at a Devanagari digit (a digit is
    never part of a word-final case ending and is the most common first
    character of an actual value — extent, survey numbers, dates)."""
    extended = 0
    while extended < MAX_SUFFIX_EXTEND and end < len(line):
        code = ord(line[end])
        if code in _DEVANAGARI_DIGITS:
            break
        if not (0x0900 <= code <= 0x097F):
            break
        end += 1
        extended += 1
    return end


# Devanagari combining marks (vowel signs, virama, visarga, anusvara,
# candrabindu, avagraha) that can't stand on their own as a value. If
# everything left over after stripping is drawn from this set — no
# independent letter or digit — it's leftover suffix debris, not a real
# reading, and should be treated as "not found" rather than returned.
_COMBINING_ONLY_RANGES = [(0x093A, 0x094F), (0x0951, 0x0957), (0x0962, 0x0963)]


def _looks_like_junk(candidate: str) -> bool:
    if len(candidate) > 3:
        return False
    for ch in candidate:
        if ch.isalnum() and not any(lo <= ord(ch) <= hi for lo, hi in _COMBINING_ONLY_RANGES):
            return False
    return True


def _label_confirms(text: str, field: FieldName) -> bool:
    """True if the field's label keyword shows up anywhere in the document
    (not necessarily on the same line as the regex match) — used as
    corroborating evidence to boost a format-match's confidence."""
    lowered = _normalize_matra(text.lower())
    return any(_normalize_matra(kw.lower()) in lowered for kw in LABEL_KEYWORDS[field])


def _confidence(base: float, *, corroborated: bool) -> float:
    """Boosts a base confidence when a second, independent signal (the
    field's label appearing elsewhere in the text) agrees with a
    format-regex match, capped just under 1.0 since this is still a
    heuristic stub rather than a verified read."""
    if not corroborated:
        return base
    return round(min(0.97, base + 0.15), 4)


def _normalize_date(match: re.Match) -> str:
    groups = match.groups()
    if len(groups[0]) == 4:  # YYYY-MM-DD
        year, month, day = groups
    else:  # DD-MM-YYYY
        day, month, year = groups
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return match.group(0)


def _label_anchored_match(text_digits: str, keywords: list[str], pattern: re.Pattern) -> re.Match | None:
    """Looks for `pattern` on the same line as a label keyword, or the next
    non-empty line, before any caller falls back to a document-wide search.

    property_id / survey_number / extent used to run `pattern.search()`
    against the *whole* document with no label anchoring at all — so any
    other number on the page that happened to match the same shape (a
    stamp reference, a document number, a footer code) could win over the
    real value sitting next to the actual label, and the confidence-boost
    logic would then treat the label appearing *anywhere* in the document
    as corroboration even though it was nowhere near the matched text. A
    real scan hit exactly this: the survey number field returned a
    same-shaped number from elsewhere on the page instead of the value
    actually printed next to "सर्वेक्षण-क्रमांक". Anchoring first closes that.

    Takes an already digit-normalized copy of the text (`text_digits`) so
    line offsets line up with what the numeric regexes expect; keyword
    matching is also matra-normalized for the same reason as
    `_find_label_value` above.
    """
    lines = text_digits.splitlines()
    for i, line in enumerate(lines):
        normalized_line = _normalize_matra(line.lower())
        if not any(_normalize_matra(kw.lower()) in normalized_line for kw in keywords):
            continue
        m = pattern.search(line)
        if m:
            return m
        for next_line in lines[i + 1 : i + 3]:
            m = pattern.search(next_line)
            if m:
                return m
    return None


def extract_fields(raw_text: str) -> FieldReadings:
    """The stubbed extraction-assist pass. Returns one FieldReading per
    FieldName; unresolved fields come back with value=None and a low
    confidence rather than being omitted, so callers always get a complete
    set to persist (and so gap-filling engines know what's still missing)."""
    readings: FieldReadings = {}
    text = raw_text or ""
    # Regex passes run against a digit-normalized copy so Devanagari/Urdu
    # numerals match the same ASCII-digit patterns as Latin numerals; label
    # search still runs against the original text since labels are matched
    # by keyword, not digit shape.
    text_digits = _normalize_digits(text)

    def make(field: FieldName, value: str | None, confidence: float) -> None:
        readings[field] = FieldReading(value=value, confidence=confidence, source=ExtractionSource.shasan_slm)

    property_anchored = _label_anchored_match(text_digits, LABEL_KEYWORDS[FieldName.property_id], PROPERTY_ID_RE)
    property_match = property_anchored or PROPERTY_ID_RE.search(text_digits)
    if property_match:
        # An anchored hit is itself the corroborating evidence (we know
        # it's next to the label); an unanchored hit falls back to the
        # weaker "label appears somewhere in the doc" signal as before.
        corroborated = bool(property_anchored) or _label_confirms(text, FieldName.property_id)
        conf = _confidence(0.82, corroborated=corroborated)
        make(FieldName.property_id, property_match.group(0), conf)
    else:
        labeled = _find_label_value(text, LABEL_KEYWORDS[FieldName.property_id])
        make(FieldName.property_id, labeled, 0.55 if labeled else 0.15)

    survey_anchored = _label_anchored_match(text_digits, LABEL_KEYWORDS[FieldName.survey_number], SURVEY_NUMBER_RE)
    survey_match = survey_anchored or SURVEY_NUMBER_RE.search(text_digits)
    if survey_match:
        corroborated = bool(survey_anchored) or _label_confirms(text, FieldName.survey_number)
        conf = _confidence(0.75, corroborated=corroborated)
        make(FieldName.survey_number, survey_match.group(0), conf)
    else:
        labeled = _find_label_value(text, LABEL_KEYWORDS[FieldName.survey_number])
        make(FieldName.survey_number, labeled, 0.5 if labeled else 0.15)

    extent_anchored = _label_anchored_match(text_digits, LABEL_KEYWORDS[FieldName.extent], EXTENT_RE)
    extent_match = extent_anchored or EXTENT_RE.search(text_digits)
    if extent_match:
        corroborated = bool(extent_anchored) or _label_confirms(text, FieldName.extent)
        conf = _confidence(0.78, corroborated=corroborated)
        make(FieldName.extent, extent_match.group(0).strip(), conf)
    else:
        labeled = _find_label_value(text, LABEL_KEYWORDS[FieldName.extent])
        make(FieldName.extent, labeled, 0.5 if labeled else 0.15)

    date_value, date_conf = None, 0.15
    for pattern in DATE_PATTERNS:
        m = pattern.search(text_digits)
        if m:
            date_value = _normalize_date(m)
            date_conf = _confidence(0.72, corroborated=_label_confirms(text, FieldName.registration_date))
            break
    if not date_value:
        labeled = _find_label_value(text, LABEL_KEYWORDS[FieldName.registration_date])
        if labeled:
            date_value, date_conf = labeled, 0.4
    make(FieldName.registration_date, date_value, date_conf)

    mutawalli = _find_label_value(text, LABEL_KEYWORDS[FieldName.mutawalli_name])
    make(FieldName.mutawalli_name, mutawalli, 0.6 if mutawalli else 0.15)

    village = _find_label_value(text, LABEL_KEYWORDS[FieldName.village])
    make(FieldName.village, village, 0.6 if village else 0.15)

    return readings
