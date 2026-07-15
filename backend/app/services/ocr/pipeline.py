"""
Orchestrates a single document through: script detection -> primary OCR
(Sarvam Vision 3B first; if its own confidence comes back below the
configured fallback threshold, Tesseract and Gemini Vision are also run and
whichever scores highest confidence is used — Sarvam remains the preferred
choice on ties) -> field extraction (Shasan-SLM stub, gap-filled by Gemini
Vision when available) -> a complete, always-six-field result ready
to persist.

This replaced an earlier "first engine that returns any non-empty text
wins" waterfall, and a supervisor-facing "pick the primary engine" admin
setting that never actually fed into this pipeline at all (the UI control
only wrote to a demo/mock store) — engine selection is now automatic and
confidence-driven instead of a manual, disconnected setting.

Gemini Vision replaced GPT-4o mini as the third engine here (GPT-4o mini
calls were failing in practice) — see gemini_engine.py. Nothing else in
this orchestration changed as part of that swap.

Deliberately synchronous — the router endpoint that calls this is a plain
`def` (not `async def`), so FastAPI/Starlette runs it in a worker thread and
the blocking network calls inside (Sarvam's job polling, Gemini's HTTP
calls) don't block the event loop. This keeps Segment 2 dependency-free
(no Celery/Redis), matching the stack in the project doc, while still
meeting the Wk-12 demo-gate's "<30 seconds" target per document.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.models import ExtractionSource, FieldName, ScriptType
from . import gemini_engine, sarvam_engine, shasan_stub, tesseract_engine
from .base import FieldReading, FieldReadings, RawTextResult

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

    fields = shasan_stub.extract_fields(primary.text)

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
