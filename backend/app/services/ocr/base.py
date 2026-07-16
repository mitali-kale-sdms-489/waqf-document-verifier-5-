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
