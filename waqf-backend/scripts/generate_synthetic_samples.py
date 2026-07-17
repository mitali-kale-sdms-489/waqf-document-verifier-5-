"""
Week 1-8 deliverable: "100-document synthetic sample set built
(template-generated Waqf-style records in Urdu + Marathi with known ground
truth)" — see the project doc's Deliverables table.

This was the one piece of the whole POC that didn't exist as a script
anywhere: Segments 1-4 of the backend were built against a handful of
ad-hoc uploaded PDFs, and the Week-9 CER benchmark / Week-10 accuracy
numbers were seeded placeholders because there was no ground-truth set to
measure them against.

What this script does
----------------------
1. Renders `n_clean` template Waqf-style records (default 80) as PNG
   "scans" — half Urdu/Nastaliq, half Marathi/Devanagari — using the exact
   field-value shapes `app/services/ocr/shasan_stub.py` already expects
   (property IDs like WQ/MH/2024/00812, survey numbers like 412/2-A,
   extents like "0.82 ha", labels drawn from shasan_stub.LABEL_KEYWORDS),
   so the generated set is realistic input for the real pipeline rather
   than text the extractor was never going to have a chance at.
2. Renders `n_seeded_error` additional documents (default 20, matching the
   Week-10 DoD: "validation rules firing correctly on 20 seeded-error
   documents") — each is a clean record with exactly one deliberate defect
   applied (missing mandatory field, malformed survey number, an
   out-of-range date, or a duplicated property ID against another document
   in the set), tagged with which rule *should* catch it.
3. Writes every image to storage/synthetic/ and a single
   ground_truth.json manifest alongside them with the exact field values
   used to render each image — the ground truth the CER benchmark and
   field-accuracy scoring in the other two scripts in this folder diff
   OCR output against.

Font requirement (read this before running for real)
------------------------------------------------------
Proper Urdu Nastaliq and Devanagari rendering needs real fonts installed,
e.g.:
    Urdu:     Noto Nastaliq Urdu (fonts-noto-unhinted / notonastaliqurdu)
    Marathi:  Noto Sans Devanagari (fonts-noto-core)
Point this script at them with NOTO_URDU_FONT / NOTO_DEVANAGARI_FONT env
vars, or install them system-wide so fontconfig finds them automatically.
Proper Arabic *shaping* (joining isolated letterforms into the connected
Nastaliq forms a reader — and Tesseract's Arabic model — expects) also
needs `arabic_reshaper` + `python-bidi` (`pip install arabic-reshaper
python-bidi`); without them, Urdu text still renders with 100% correct
Unicode codepoints (the ground truth is unaffected) but as disconnected
isolated letterforms, which will inflate Urdu CER relative to a real scan.
Without correct fonts installed at all, PIL falls back to whatever
Unicode-coverage font it can find (e.g. GNU FreeSerif) and logs a warning
per script the first time it's used — ground truth stays correct either
way, but don't trust the *rendered image* for a real CER benchmark until
proper fonts are installed.

Usage
-----
    python -m scripts.generate_synthetic_samples
    python -m scripts.generate_synthetic_samples --n-clean 80 --n-seeded-error 20
"""
from __future__ import annotations

import argparse
import json
import logging
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("generate_synthetic_samples")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "storage" / "synthetic"

# ---------------------------------------------------------------------------
# Word banks — enough variety for 100 non-repeating-looking documents, not
# meant to be exhaustive. Deliberately real Urdu/Marathi vocabulary (not
# transliteration) so OCR has real script to read.
# ---------------------------------------------------------------------------

URDU_MUTAWALLI_NAMES = [
    "سید عبدالرحیم شاہ", "محمد یوسف قریشی", "غلام مصطفی خان", "عبدالستار انصاری",
    "شیخ محمد اسلم", "سید اختر حسین", "محمد ادریس شیخ", "عبدالغفار میمن",
    "حاجی محمد رفیق", "سید نور محمد شاہ", "عبدالکریم پٹھان", "محمد اسحاق قادری",
]
URDU_VILLAGES = [
    "قصبہ نظام آباد", "موضع شاہ پور", "قصبہ اورنگ آباد", "موضع بہادر پور",
    "قصبہ رحیم آباد", "موضع خیر پور", "قصبہ فتح گڑھ", "موضع امام باڑہ",
]

MARATHI_MUTAWALLI_NAMES = [
    "शेख अब्दुल रहीम", "मोहम्मद युसूफ पठाण", "इनामदार गुलाब शेख", "काझी अब्दुल सत्तार",
    "शेख मोहम्मद अस्लम", "सय्यद अख्तर हुसेन", "मोमीन अब्दुल गफार", "देशमुख रफिक शेख",
    "सय्यद नूर मोहम्मद", "पिंजारी अब्दुल करीम",
]
MARATHI_VILLAGES = [
    "मौजे शहापूर", "मौजे बहादूरपूर", "मौजे रहीमपूर", "मौजे खैरपूर",
    "मौजे फतेहगड", "मौजे इमामवाडा", "मौजे निजामाबाद", "मौजे औरंगाबाद",
]

DISTRICT_CODES = ["MH", "UP", "KA", "TG", "AP", "WB"]


def _rand_property_id(rng: random.Random) -> str:
    return f"WQ/{rng.choice(DISTRICT_CODES)}/{rng.randint(1990, 2024)}/{rng.randint(100, 99999):05d}"


def _rand_survey_number(rng: random.Random) -> str:
    block = rng.randint(1, 999)
    sub = rng.randint(1, 9)
    suffix = rng.choice(["A", "B", "C"])
    return rng.choice([f"{block}/{sub}", f"{block}/{sub}-{suffix}"])


def _rand_date(rng: random.Random, *, plausible: bool = True) -> str:
    if plausible:
        year = rng.randint(1981, 2023)
    else:
        # Deliberately out of the plausible range for a seeded-error doc.
        year = rng.choice([rng.randint(1900, 1979), 2027 + rng.randint(0, 3)])
    month, day = rng.randint(1, 12), rng.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _rand_extent(rng: random.Random, script: str) -> str:
    value = f"{rng.uniform(0.1, 9.9):.2f}"
    unit = "ha" if script == "urdu_nastaliq" else rng.choice(["गुंठे", "एकर", "ha"])
    return f"{value} {unit}"


@dataclass
class GroundTruthDoc:
    doc_id: str
    filename: str
    script_type: str  # "urdu_nastaliq" | "marathi_devanagari"
    is_synthetic: bool = True
    seeded_error_type: str | None = None
    expected_failing_rule: str | None = None
    fields: dict = field(default_factory=dict)  # {field_name: value_or_None}
    rendered_text: str = ""  # full-page ground-truth text, for CER scoring


def _build_clean_record(rng: random.Random, script: str, index: int) -> GroundTruthDoc:
    property_id = _rand_property_id(rng)
    survey_number = _rand_survey_number(rng)
    date = _rand_date(rng, plausible=True)
    extent = _rand_extent(rng, script)

    if script == "urdu_nastaliq":
        mutawalli = rng.choice(URDU_MUTAWALLI_NAMES)
        village = rng.choice(URDU_VILLAGES)
        lines = [
            "وقف رجسٹر - جائیداد کا اندراج",
            f"جائیداد نمبر: {property_id}",
            f"متولی: {mutawalli}",
            f"سروے نمبر: {survey_number}",
            f"تاریخ اندراج: {date}",
            f"رقبہ: {extent}",
            f"گاؤں: {village}",
        ]
        doc_id = f"urd-{index:03d}"
    else:
        mutawalli = rng.choice(MARATHI_MUTAWALLI_NAMES)
        village = rng.choice(MARATHI_VILLAGES)
        lines = [
            "वक्फ नोंदणी - मालमत्ता तपशील",
            f"मालमत्ता: {property_id}",
            f"मुतवल्ली नाव: {mutawalli}",
            f"सर्वे क्रमांक: {survey_number}",
            f"नोंदणी तारीख: {date}",
            f"क्षेत्रफळ: {extent}",
            f"गाव: {village}",
        ]
        doc_id = f"mar-{index:03d}"

    return GroundTruthDoc(
        doc_id=doc_id,
        filename=f"synthetic-{doc_id}.png",
        script_type=script,
        fields={
            "property_id": property_id,
            "mutawalli_name": mutawalli,
            "survey_number": survey_number,
            "registration_date": date,
            "extent": extent,
            "village": village,
        },
        rendered_text="\n".join(lines),
    )


def _apply_seeded_error(rng: random.Random, base: GroundTruthDoc, other_property_ids: list[str]) -> GroundTruthDoc:
    """Corrupt a copy of a clean record with exactly one defect, tagged
    with which validation rule (app/services/validation.py) should catch
    it — this is the ground truth the Week-10 "20 seeded-error documents"
    DoD and the Week-12 "≥18/20 seeded-error catch rate" gate are scored
    against."""
    doc = GroundTruthDoc(**{**asdict(base), "fields": dict(base.fields)})
    doc.seeded_error_type = ""  # set below
    lines = doc.rendered_text.splitlines()

    error_kind = rng.choice(["missing_mandatory", "bad_survey_format", "bad_date", "duplicate_property_id"])

    if error_kind == "missing_mandatory":
        drop_field = rng.choice(["property_id", "mutawalli_name", "survey_number"])
        doc.fields[drop_field] = None
        lines = [ln for ln in lines if not _line_matches_field(ln, drop_field)]
        doc.expected_failing_rule = "mandatory_fields_present"

    elif error_kind == "bad_survey_format":
        bad_survey = str(rng.randint(10000, 99999))  # doesn't match SURVEY_NUMBER_RE at all
        doc.fields["survey_number"] = bad_survey
        lines = [_replace_field_line(ln, "survey_number", bad_survey) for ln in lines]
        doc.expected_failing_rule = "survey_number_format"

    elif error_kind == "bad_date":
        bad_date = _rand_date(rng, plausible=False)
        doc.fields["registration_date"] = bad_date
        lines = [_replace_field_line(ln, "registration_date", bad_date) for ln in lines]
        doc.expected_failing_rule = "date_plausibility"

    else:  # duplicate_property_id
        dup_id = rng.choice(other_property_ids)
        doc.fields["property_id"] = dup_id
        lines = [_replace_field_line(ln, "property_id", dup_id) for ln in lines]
        doc.expected_failing_rule = "cross_document_consistency"

    doc.seeded_error_type = error_kind
    doc.rendered_text = "\n".join(lines)
    doc.doc_id = f"{base.doc_id}-err-{error_kind}"
    doc.filename = f"synthetic-{doc.doc_id}.png"
    return doc


_FIELD_TO_PREFIXES = {
    "property_id": ["جائیداد نمبر:", "मालमत्ता:"],
    "mutawalli_name": ["متولی:", "मुतवल्ली नाव:"],
    "survey_number": ["سروے نمبر:", "सर्वे क्रमांक:"],
    "registration_date": ["تاریخ اندراج:", "नोंदणी तारीख:"],
    "extent": ["رقبہ:", "क्षेत्रफळ:"],
    "village": ["گاؤں:", "गाव:"],
}


def _line_matches_field(line: str, field_name: str) -> bool:
    return any(line.strip().startswith(p) for p in _FIELD_TO_PREFIXES[field_name])


def _replace_field_line(line: str, field_name: str, new_value: str) -> str:
    for prefix in _FIELD_TO_PREFIXES[field_name]:
        if line.strip().startswith(prefix):
            return f"{prefix} {new_value}"
    return line


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_WARNED_SCRIPTS: set[str] = set()


def _find_font(script: str) -> Path | None:
    import os

    env_key = "NOTO_URDU_FONT" if script == "urdu_nastaliq" else "NOTO_DEVANAGARI_FONT"
    if os.environ.get(env_key):
        p = Path(os.environ[env_key])
        if p.exists():
            return p

    candidates = (
        [
            "/usr/share/fonts/opentype/noto/NotoNastaliqUrdu-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoNastaliqUrdu-Regular.ttf",
        ]
        if script == "urdu_nastaliq"
        else [
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
        ]
    )
    for c in candidates:
        if Path(c).exists():
            return Path(c)

    # Best-effort fallback with wide (if imperfect) Unicode coverage —
    # GNU FreeFont covers Devanagari reasonably and Arabic in isolated
    # forms (no contextual shaping). Loud warning, not a silent downgrade.
    fallback = Path("/usr/share/fonts/truetype/freefont/FreeSerif.ttf")
    if fallback.exists():
        if script not in _WARNED_SCRIPTS:
            _WARNED_SCRIPTS.add(script)
            logger.warning(
                "No dedicated %s font found (set %s) — falling back to FreeSerif. "
                "Ground truth text is unaffected, but the *rendered image* will not "
                "look like a real scan and Urdu will render as disconnected "
                "letterforms (no Arabic shaping). Install proper fonts before "
                "trusting a CER run against these images.",
                script,
                env_key,
            )
        return fallback

    if script not in _WARNED_SCRIPTS:
        _WARNED_SCRIPTS.add(script)
        logger.warning("No usable font found at all for %s — skipping image rendering for this doc.", script)
    return None


def _maybe_reshape_urdu(text: str) -> str:
    """Best-effort Arabic contextual shaping + bidi reordering for display.
    Ground truth in the manifest is always the plain logical-order text
    regardless of whether this succeeds."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text  # falls back to isolated letterforms, see module docstring


def render_document_image(doc: GroundTruthDoc, out_path: Path, rng: random.Random) -> bool:
    font_path = _find_font(doc.script_type)
    if font_path is None:
        return False

    width, height = 1240, 1754  # ~A4 at 150dpi, matches a real scanned register page
    img = Image.new("L", (width, height), color=250)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), 34)

    # Light scan-noise texture so this isn't a pristine vector render —
    # cheap stand-in for real scan artefacts (dust, uneven lighting).
    for _ in range(width * height // 400):
        x, y = rng.randint(0, width - 1), rng.randint(0, height - 1)
        img.putpixel((x, y), rng.randint(215, 245))

    y = 120
    rtl = doc.script_type == "urdu_nastaliq"
    for line in doc.rendered_text.splitlines():
        display_line = _maybe_reshape_urdu(line) if rtl else line
        if rtl:
            bbox = draw.textbbox((0, 0), display_line, font=font)
            x = width - 120 - (bbox[2] - bbox[0])
        else:
            x = 120
        draw.text((x, y), display_line, font=font, fill=20)
        y += 70

    img.save(out_path)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(n_clean: int, n_seeded_error: int, seed: int, out_dir: Path) -> list[GroundTruthDoc]:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_docs: list[GroundTruthDoc] = []
    for i in range(n_clean):
        script = "urdu_nastaliq" if i % 2 == 0 else "marathi_devanagari"
        clean_docs.append(_build_clean_record(rng, script, i))

    all_property_ids = [d.fields["property_id"] for d in clean_docs]
    seeded_docs: list[GroundTruthDoc] = []
    for i in range(n_seeded_error):
        base = clean_docs[i % len(clean_docs)]
        others = [pid for pid in all_property_ids if pid != base.fields["property_id"]]
        seeded_docs.append(_apply_seeded_error(rng, base, others))

    all_docs = clean_docs + seeded_docs
    rendered = 0
    for doc in all_docs:
        if render_document_image(doc, out_dir / doc.filename, rng):
            rendered += 1

    manifest_path = out_dir / "ground_truth.json"
    manifest_path.write_text(
        json.dumps([asdict(d) for d in all_docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "Generated %d documents (%d clean + %d seeded-error), rendered %d images -> %s; manifest -> %s",
        len(all_docs), len(clean_docs), len(seeded_docs), rendered, out_dir, manifest_path,
    )
    return all_docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-clean", type=int, default=80)
    parser.add_argument("--n-seeded-error", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    generate(args.n_clean, args.n_seeded_error, args.seed, args.out_dir)


if __name__ == "__main__":
    main()
