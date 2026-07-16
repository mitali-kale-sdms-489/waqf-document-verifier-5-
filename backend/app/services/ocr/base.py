"""Shared types passed between OCR engine adapters and the pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import ExtractionSource, FieldName, ScriptType

# Free-text name/place fields where an engine "helpfully" transliterating
# instead of transcribing is a real risk (property_id/survey_number/
# registration_date/extent are often legitimately Latin/numeric even in a
# Urdu/Devanagari document, so the check below doesn't apply to them).
SCRIPT_SENSITIVE_FIELDS = {FieldName.mutawalli_name, FieldName.village}

_LATIN_LETTERS_RE = re.compile(r"[A-Za-z]")
_NATIVE_SCRIPT_RANGES: dict[ScriptType, re.Pattern[str]] = {
    ScriptType.urdu_nastaliq: re.compile(r"[\u0600-\u06FF\u0750-\u077F]"),
    ScriptType.marathi_devanagari: re.compile(r"[\u0900-\u097F]"),
    ScriptType.hindi_devanagari: re.compile(r"[\u0900-\u097F]"),
    ScriptType.sanskrit_devanagari: re.compile(r"[\u0900-\u097F]"),
}


def looks_transliterated(value: str, script_type: ScriptType) -> bool:
    """True if `value` is pure Latin script with no native-script
    characters at all, for a document whose script_type is NOT
    english_latin. That combination means an engine rendered a name/place
    straight into English instead of transcribing it as written — every
    engine's prompt says not to do this, but LLMs auto-"correcting"
    recognizable proper names into their familiar English spelling is a
    known failure mode, not a hypothetical one. Shared by qwen_mapper.py
    (which can retry immediately, since it already has the source OCR
    text) and pipeline.py (which uses it as a last-resort safety net after
    every engine has had a chance)."""
    native_re = _NATIVE_SCRIPT_RANGES.get(script_type)
    if native_re is None:  # english_latin, or an unrecognized type — nothing to flag
        return False
    return bool(_LATIN_LETTERS_RE.search(value)) and not native_re.search(value)


# Distinct failure mode from `looks_transliterated` above: that function
# only catches a value rendered *fully in Latin*. It says nothing about a
# value rendered fluently in the *other* non-Latin script — e.g. an engine
# given a bad language hint transcribes a Devanagari (Sanskrit/Hindi/
# Marathi) document's name field in Urdu Nastaliq instead, or vice versa.
# That reading looks perfectly legitimate (real letters, real script, high
# engine confidence) and was passing through completely unchecked before
# this was added.
_SCRIPT_BLOCK_RANGES: dict[str, list[tuple[int, int]]] = {
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "devanagari": [(0x0900, 0x097F)],
}

_EXPECTED_BLOCK: dict[ScriptType, str] = {
    ScriptType.urdu_nastaliq: "arabic",
    ScriptType.marathi_devanagari: "devanagari",
    ScriptType.hindi_devanagari: "devanagari",
    ScriptType.sanskrit_devanagari: "devanagari",
}


def _count_in_block(value: str, block: str) -> int:
    ranges = _SCRIPT_BLOCK_RANGES[block]
    return sum(1 for ch in value if any(lo <= ord(ch) <= hi for lo, hi in ranges))


def foreign_script_block(value: str, script_type: ScriptType) -> str | None:
    """Returns "arabic" or "devanagari" — whichever wrong-script block
    `value` contains characters from — if `value` contains any character
    from a non-Latin script block OTHER than the one `script_type` expects.
    Returns None for english_latin documents (nothing to check here;
    Latin-vs-native is `looks_transliterated`'s job) and for values with no
    such contamination. This is what catches "Urdu text on a Sanskrit
    document" and equivalents, which `looks_transliterated` cannot see
    since that text isn't Latin at all."""
    expected = _EXPECTED_BLOCK.get(script_type)
    if expected is None:
        return None
    for block in _SCRIPT_BLOCK_RANGES:
        if block == expected:
            continue
        if _count_in_block(value, block) > 0:
            return block
    return None


@dataclass
class RawTextResult:
    """Output of a full-page OCR pass, before field extraction."""

    text: str
    engine: ExtractionSource
    confidence: float  # 0..1, engine's own estimate of overall read quality
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.error is None


@dataclass
class FieldReading:
    value: str | None
    confidence: float
    source: ExtractionSource
    # English rendering of `value` — a transliteration for name/place fields
    # (e.g. "Haji Muhammad Rafiq") rather than a meaning-translation, and a
    # plain digit/ISO-format conversion for numeric/date fields written in
    # Urdu or Devanagari numerals. Populated by gemini_engine.translate_fields
    # as a post-extraction pass (see pipeline.py); None until then, and
    # stays None for documents already in English/Latin script or when the
    # translation call fails/isn't configured.
    value_en: str | None = None


FieldReadings = dict[FieldName, FieldReading]


# Devanagari digits (U+0966-096F), Arabic-Indic digits (U+0660-0669), and
# Extended/Urdu-Indic digits (U+06F0-06F9) all map onto 0-9 in the same
# order. Used as an offline fallback for value_en on numeric/date-shaped
# fields (property_id, survey_number, registration_date, extent) when
# Gemini's translation pass is unavailable (not configured, rate-limited,
# or the call otherwise fails) — see pipeline.py. This can't help
# mutawalli_name/village (those need real transliteration, not digit
# conversion), but it means the reviewer isn't left with a completely
# blank English column for every field just because one external API call
# didn't go through.
_DIGIT_MAP = {}
for _i in range(10):
    _DIGIT_MAP[chr(0x0966 + _i)] = str(_i)  # Devanagari
    _DIGIT_MAP[chr(0x0660 + _i)] = str(_i)  # Arabic-Indic
    _DIGIT_MAP[chr(0x06F0 + _i)] = str(_i)  # Extended Arabic-Indic (Urdu)
del _i


def convert_indic_digits(value: str) -> str | None:
    """Returns `value` with any Devanagari/Arabic-Indic/Urdu-Indic digits
    replaced by their plain Western (0-9) equivalents, leaving every other
    character untouched. Returns None if `value` contained no such digits
    at all (nothing useful to offer as a fallback rendering in that case —
    the caller should leave value_en unset rather than show an identical
    copy of the original)."""
    if not any(ch in _DIGIT_MAP for ch in value):
        return None
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in value)
