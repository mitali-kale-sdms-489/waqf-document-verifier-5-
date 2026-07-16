"""
Orchestrates a single document through: script detection -> primary OCR
(Sarvam Vision 3B first; if its own confidence comes back below the
configured fallback threshold, Tesseract and Gemini Vision are also run and
whichever scores highest confidence is used — Sarvam remains the preferred
choice on ties) -> field extraction (Qwen2.5 via a local Ollama server,
gap-filled by Gemini Vision when available) -> a complete, always-six-field
result ready to persist.

This replaced an earlier "first engine that returns any non-empty text
wins" waterfall, and a supervisor-facing "pick the primary engine" admin
setting that never actually fed into this pipeline at all (the UI control
only wrote to a demo/mock store) — engine selection is now automatic and
confidence-driven instead of a manual, disconnected setting.

Gemini Vision replaced GPT-4o mini as the third engine here (GPT-4o mini
calls were failing in practice) — see gemini_engine.py. Nothing else in
this orchestration changed as part of that swap.

Field extraction previously ran through shasan_stub.py, a regex/heuristic
parser. That's been replaced by qwen_mapper.py, which sends the winning
engine's raw OCR text (text only, no image) to a locally-running Qwen2.5
model via Ollama's HTTP API and parses its JSON response into the same
FieldReadings shape. shasan_stub.py is left in the tree for compatibility
but is no longer called from here. See qwen_mapper.py for the prompt,
JSON parsing, and Ollama-unavailable fallback behavior.

Deliberately synchronous — the router endpoint that calls this is a plain
`def` (not `async def`), so FastAPI/Starlette runs it in a worker thread and
the blocking network calls inside (Sarvam's job polling, Gemini's HTTP
calls, now also Ollama's HTTP call) don't block the event loop. This keeps
Segment 2 dependency-free (no Celery/Redis), matching the stack in the
project doc, while still meeting the Wk-12 demo-gate's "<30 seconds"
target per document.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.models import ExtractionSource, FieldName, ScriptType
from . import gemini_engine, qwen_mapper, sarvam_engine, tesseract_engine
from .base import SCRIPT_SENSITIVE_FIELDS, FieldReading, FieldReadings, RawTextResult, looks_transliterated

logger = logging.getLogger(__name__)
settings = get_settings()

# Below this, a field reading is treated as "the engine basically guessed"
# and worth trying to backfill with a second engine if one is available.
GAP_FILL_THRESHOLD = 0.4

# Below this, Sarvam Vision's own read confidence is treated as too low to
# trust on its own — Tesseract and Gemini Vision are also run so their
# confidence can be compared against it. Overridable per-call from the
# admin-configurable OcrSettings.ocr_fallback_threshold (falls back to this
# constant if no settings row/value is supplied, e.g. in tests).
DEFAULT_OCR_FALLBACK_THRESHOLD = 0.6


def _guard_against_transliterated_values(
    fields: FieldReadings, script_type: ScriptType, notes: list[str]
) -> None:
    """Last-resort safety net: by the time this runs, qwen_mapper.py has
    already tried to catch and retry this itself (see its own
    looks_transliterated check + one corrective retry, right where the
    OCR text is still on hand), and Gemini's gap-fill has had its own shot
    at script-sensitive fields too. If a value STILL looks transliterated
    after both of those, demote it: the Latin text is moved into value_en
    (it's already exactly what that's for), the main value is cleared, and
    confidence is dropped to well below GAP_FILL_THRESHOLD. That surfaces
    it in the review UI as "needs manual entry" — showing a fluent-looking
    but wrong value with high confidence would be worse than an honest
    blank for a record like this. Never raises; a no-op if nothing in
    `fields` trips the check."""
    for field in SCRIPT_SENSITIVE_FIELDS:
        reading = fields.get(field)
        if reading is None or not reading.value:
            continue
        if looks_transliterated(reading.value, script_type):
            notes.append(
                f"{field.value}: engine returned a Latin-script reading ('{reading.value}') for a "
                f"{script_type.value} document — treated as a transliteration, not a transcription, "
                "and cleared for manual entry (kept as the English rendering below)."
            )
            reading.value_en = reading.value_en or reading.value
            reading.value = None
            reading.confidence = min(reading.confidence, 0.2)


@dataclass
class PipelineResult:
    script_type: ScriptType
    overall_confidence: float
    fields: FieldReadings
    primary_engine: ExtractionSource
    engine_notes: list[str]


def _run_primary_ocr(
    raw_bytes: bytes,
    filename: str,
    mime_type: str | None,
    fallback_threshold: float = DEFAULT_OCR_FALLBACK_THRESHOLD,
) -> tuple[RawTextResult, ScriptType, list[str]]:
    notes: list[str] = []

    # Fast, offline pass first — gives us a script-type hint for the Sarvam
    # API call even when Tesseract's own read isn't good enough to use as
    # the primary transcription. Commonly empty if the urd/mar/eng language
    # packs aren't installed — that's fine, it's only a hint at this stage.
    quick = tesseract_engine.run_tesseract(raw_bytes, mime_type)
    early_hint = tesseract_engine.detect_script(quick.text) or tesseract_engine.detect_script_from_filename(filename)
    if not early_hint:
        notes.append("No script hint available before OCR (Tesseract produced no text and filename didn't "
                      "indicate one) — requesting Sarvam Vision with a Hindi default; scriptType will be "
                      "corrected from the actual OCR output below regardless.")

    def _final_script(result_text: str) -> ScriptType:
        # Authoritative: re-detect from whichever engine's text actually won,
        # never just reuse the pre-OCR guess. Falls back to the early hint,
        # then the filename, then a default — in that order — only if the
        # winning text itself has no detectable script (e.g. empty/garbled).
        return (
            tesseract_engine.detect_script(result_text)
            or early_hint
            or ScriptType.hindi_devanagari
        )

    # Sarvam Vision 3B is always tried first and is the preferred engine on
    # ties (see Week-9 CER benchmark: it's materially more accurate than
    # Tesseract or Gemini Vision on both Urdu Nastaliq and Marathi
    # Devanagari). But "tried first" no longer means "used unconditionally"
    # — if its own confidence comes back below `fallback_threshold`,
    # Tesseract and Gemini Vision are run too and scored against it, rather
    # than only kicking in when Sarvam errors outright.
    candidates: list[RawTextResult] = []

    sarvam_result = sarvam_engine.run_sarvam_vision(raw_bytes, filename, early_hint)
    if sarvam_result.ok:
        candidates.append(sarvam_result)
        notes.append(f"Sarvam Vision confidence: {sarvam_result.confidence:.2f}.")
    else:
        notes.append(f"Sarvam Vision unavailable ({sarvam_result.error}).")

    needs_comparison = not candidates or candidates[0].confidence < fallback_threshold
    if needs_comparison:
        if not candidates:
            notes.append("Sarvam Vision unavailable — comparing Tesseract and Gemini Vision instead.")
        else:
            notes.append(
                f"Sarvam Vision confidence ({sarvam_result.confidence:.2f}) is below the "
                f"{fallback_threshold:.2f} fallback threshold — comparing against Tesseract and Gemini Vision."
            )

        if quick.ok:
            candidates.append(quick)
            notes.append(f"Tesseract confidence: {quick.confidence:.2f}.")
        else:
            notes.append(f"Tesseract unavailable ({quick.error}).")

        gemini_result = gemini_engine.run_gemini_ocr(raw_bytes, mime_type)
        if gemini_result.ok:
            candidates.append(gemini_result)
            notes.append(f"Gemini Vision confidence: {gemini_result.confidence:.2f}.")
        else:
            notes.append(f"Gemini Vision unavailable ({gemini_result.error}).")

    if not candidates:
        notes.append("All OCR engines failed or are unconfigured.")
        fallback_result = gemini_result if needs_comparison else sarvam_result
        return fallback_result, (early_hint or ScriptType.hindi_devanagari), notes

    # max() returns the first-encountered item on ties, and candidates is
    # always appended in Sarvam -> Tesseract -> Gemini Vision order, so ties
    # naturally resolve in that preference order without extra logic.
    best = max(candidates, key=lambda r: r.confidence)
    if len(candidates) > 1 and best is not candidates[0]:
        notes.append(f"{best.engine.value} scored the highest confidence ({best.confidence:.2f}) and was used.")
    elif needs_comparison and len(candidates) > 1:
        notes.append(f"Sarvam Vision remained the best/tied result ({best.confidence:.2f}) and was used.")

    return best, _final_script(best.text), notes


def process_document(
    raw_bytes: bytes,
    filename: str,
    mime_type: str | None,
    ocr_fallback_threshold: float = DEFAULT_OCR_FALLBACK_THRESHOLD,
) -> PipelineResult:
    primary, script_type, notes = _run_primary_ocr(raw_bytes, filename, mime_type, ocr_fallback_threshold)

    # Mapping stage: Qwen2.5 (via Ollama) turns the raw OCR text into
    # structured fields. This replaced shasan_stub's regex/heuristic parse
    # — shasan_stub.py is kept in the tree for compatibility but is no
    # longer wired into the pipeline. See qwen_mapper.py for the JSON
    # contract, prompt, and failure handling (Ollama unavailable -> all
    # fields come back empty/0.0 confidence, never raises).
    fields = qwen_mapper.extract_fields(primary.text, script_type)

    weak_fields = [f for f, r in fields.items() if r.confidence < GAP_FILL_THRESHOLD]
    if weak_fields and settings.gemini_configured:
        gemini_fields = gemini_engine.run_gemini_field_extraction(raw_bytes, mime_type)
        if gemini_fields:
            for field in weak_fields:
                candidate = gemini_fields.get(field)
                if candidate and candidate.confidence > fields[field].confidence:
                    fields[field] = candidate
            notes.append("Gemini Vision used to backfill low-confidence field(s): "
                         + ", ".join(f.value for f in weak_fields))
        else:
            notes.append("Gemini Vision field-extraction backfill attempted but failed or not configured.")

    # Guarantee every FieldName is present even if something upstream
    # skipped it (defensive — extract_fields already covers all six).
    for field in FieldName:
        fields.setdefault(field, FieldReading(value=None, confidence=0.0, source=primary.engine))

    # Catch an engine "helpfully" transliterating a name/place field
    # straight into English instead of transcribing it as written — before
    # the translation pass below, so a value already caught here doesn't
    # get translated twice or overwrite the transliteration we just moved
    # into value_en.
    if script_type != ScriptType.english_latin:
        _guard_against_transliterated_values(fields, script_type, notes)

    # Translation pass: best-effort English transliteration of whatever got
    # extracted, via Gemini (see gemini_engine.run_gemini_translation).
    # Skipped entirely for documents already in English/Latin script —
    # there's nothing to translate. Gemini not configured, or the call
    # failing, just leaves value_en as None on every field; it never blocks
    # or fails the pipeline.
    if script_type != ScriptType.english_latin and settings.gemini_configured:
        translations = gemini_engine.run_gemini_translation(fields)
        if translations:
            for field, value_en in translations.items():
                fields[field].value_en = value_en
            notes.append("Gemini translation pass populated English renderings for: "
                         + ", ".join(f.value for f in translations))
        else:
            notes.append("Gemini translation pass attempted but returned nothing (call failed, not "
                         "configured, or no fields to translate).")

    overall_confidence = round(sum(r.confidence for r in fields.values()) / len(fields), 4)

    if not primary.ok:
        notes.append("All OCR engines failed or are unconfigured — document queued for fully manual entry.")

    return PipelineResult(
        script_type=script_type,
        overall_confidence=overall_confidence,
        fields=fields,
        primary_engine=primary.engine,
        engine_notes=notes,
    )
