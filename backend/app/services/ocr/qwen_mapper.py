"""
Qwen2.5 (via a locally-running Ollama server) field-extraction mapper.

Replaces shasan_stub.py as the pipeline's mapping stage: instead of a
regex/heuristic parse of the raw OCR text, the OCR text is handed to a
local Qwen2.5 model through Ollama's HTTP API and asked to return the six
Waqf record fields as JSON. shasan_stub.py is left in place (unused) per
the migration requirement to keep it around for compatibility rather than
delete it outright.

Input contract: this module receives ONLY the raw OCR text string that
Sarvam Vision (or whichever engine won `_run_primary_ocr`) produced — no
image bytes, no document metadata. That keeps it a drop-in replacement for
`shasan_stub.extract_fields(text: str) -> FieldReadings` in pipeline.py.

Failure handling: Ollama being unreachable (server not running, wrong
port, model not pulled, timeout) is treated as a normal, expected
condition — not an exception the caller has to handle. Every failure mode
below logs and returns a complete FieldReadings with every field at
value=None / confidence=0.0, exactly like a "found nothing" reading from
the old stub, so pipeline.py's gap-fill logic (which backfills anything
under GAP_FILL_THRESHOLD via Gemini Vision) kicks in unchanged and the
document is never lost, just fully deferred to Gemini/manual review.

`source` on returned FieldReading objects is ExtractionSource.qwen_slm, a
dedicated enum member (see app/models.py) distinct from the old
shasan_slm value. The frontend's ExtractedField.source type
(src/types/domain.ts) has been updated to include "qwen_slm" in the same
change — see that file's diff alongside this one.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import get_settings
from app.models import ExtractionSource, FieldName, ScriptType
from .base import SCRIPT_SENSITIVE_FIELDS, FieldReading, FieldReadings, looks_transliterated

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT = settings.ollama_timeout_seconds  # configurable via OLLAMA_TIMEOUT_SECONDS; see config.py

# Confidence assigned to any field Qwen returns a non-null value for.
# Deliberately a flat constant (not graded like the old regex stub's
# per-match confidence) since an LLM extraction doesn't have an equivalent
# notion of "matched a strict format regex" vs "matched a loose label
# search" to grade against.
PRESENT_CONFIDENCE = 0.90
MISSING_CONFIDENCE = 0.0

# Field list kept in the same order as FieldName so the prompt's schema
# and the enum iteration below always agree. NOTE: mapped onto your
# project's actual six fields (property_id, mutawalli_name, survey_number,
# registration_date, extent, village) rather than the owner_name / taluka /
# district / area list, which aren't present anywhere in the schema.
_PROMPT_TEMPLATE = """You are an expert at extracting structured information from Indian Waqf land records.

Extract these fields:

- property_id
- mutawalli_name
- survey_number
- registration_date
- extent
- village

Rules:
- Return ONLY valid JSON.
- Do not explain anything.
- If a field is missing, return null.
- Preserve the original language of the values.
- Do not invent values.
- CRITICAL for mutawalli_name and village: copy the value EXACTLY, character-for-character, from the OCR \
text below, in whatever script it's written in (Urdu, Devanagari, etc). Even if you recognize the name and \
know its English spelling, do NOT romanize, transliterate, or translate it — copy the original characters \
as they appear in the text.

OCR TEXT:

{ocr_text}
"""

_RETRY_PROMPT_TEMPLATE = """Your previous answer for the field "{field_name}" was "{wrong_value}", but that \
looks like an English transliteration rather than the text actually written in the OCR text below — you \
were asked to copy the original script exactly, not romanize it.

Look again at the OCR text and find where {field_name} appears. Respond with ONLY that value, copied \
character-for-character in its original script, no JSON, no quotes, no explanation. If you genuinely cannot \
find it written in the text, respond with exactly: NONE

OCR TEXT:

{ocr_text}
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _empty_readings() -> FieldReadings:
    return {
        field: FieldReading(value=None, confidence=MISSING_CONFIDENCE, source=ExtractionSource.qwen_slm)
        for field in FieldName
    }


def _call_ollama(ocr_text: str) -> str | None:
    """POSTs to Ollama's /api/generate and returns the raw model output
    string, or None if the call failed for any reason (connection refused,
    timeout, non-2xx, malformed response body)."""
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": _PROMPT_TEMPLATE.format(ocr_text=ocr_text),
        "stream": False,
        # Ollama's JSON mode constrains sampling to valid JSON — makes the
        # parse step below far less likely to need its fallback path.
        "format": "json",
        "options": {"temperature": 0},
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as exc:
        logger.error("Ollama unreachable at %s (%s): %s", settings.ollama_url, settings.ollama_model, exc)
        return None
    except httpx.TimeoutException as exc:
        logger.error("Ollama request timed out after %.0fs (%s): %s", REQUEST_TIMEOUT, settings.ollama_model, exc)
        return None
    except httpx.HTTPStatusError as exc:
        logger.error("Ollama returned HTTP %s for model %s: %s",
                      exc.response.status_code, settings.ollama_model, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - any other transport/parse failure must not crash the pipeline
        logger.error("Unexpected error calling Ollama (%s): %s", settings.ollama_model, exc)
        return None

    response_text = data.get("response")
    if not isinstance(response_text, str) or not response_text.strip():
        logger.error("Ollama response missing/empty 'response' field for model %s: %r",
                      settings.ollama_model, data)
        return None
    return response_text


def _parse_json(response_text: str) -> dict | None:
    """Safely parses the model's output as JSON. Tries a direct parse
    first (the common case, especially with Ollama's `format: json` mode),
    then falls back to extracting the first {...} block in case the model
    wrapped the JSON in markdown fences or added stray commentary despite
    the prompt's instructions not to."""
    try:
        parsed = json.loads(response_text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(response_text)
    if not match:
        logger.error("Qwen response contained no parseable JSON object: %r", response_text[:500])
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse extracted JSON block from Qwen response: %s", exc)
        return None


def _call_ollama_plain(prompt: str) -> str | None:
    """Same as _call_ollama but without the JSON-mode constraint — used for
    the single-field corrective retry below, which asks for a bare string
    (or the literal NONE), not a JSON object."""
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - retry is best-effort, any failure just means "keep the original"
        logger.warning("Ollama retry call failed (%s): %s", settings.ollama_model, exc)
        return None

    response_text = data.get("response")
    if not isinstance(response_text, str) or not response_text.strip():
        return None
    return response_text.strip().strip('"').strip()


def _retry_native_script_field(ocr_text: str, field: FieldName, wrong_value: str) -> str | None:
    """One corrective follow-up call, scoped to a single field, used when
    Qwen's first answer for a script-sensitive field (mutawalli_name,
    village) came back transliterated into Latin script instead of copied
    verbatim (see base.looks_transliterated). Returns the corrected
    native-script value, or None if the retry also failed / the model
    genuinely couldn't find it (responded NONE) / errored out — in every
    None case the caller keeps treating the original reading as suspect
    and pipeline.py's guard is the final safety net."""
    prompt = _RETRY_PROMPT_TEMPLATE.format(field_name=field.value, wrong_value=wrong_value, ocr_text=ocr_text)
    response_text = _call_ollama_plain(prompt)
    if response_text is None:
        return None
    if response_text.strip().upper() == "NONE":
        return None
    return response_text


def _to_field_readings(parsed: dict) -> FieldReadings:
    readings: FieldReadings = {}
    for field in FieldName:
        raw_value = parsed.get(field.value)
        value = raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None
        confidence = PRESENT_CONFIDENCE if value else MISSING_CONFIDENCE
        readings[field] = FieldReading(value=value, confidence=confidence, source=ExtractionSource.qwen_slm)
    return readings


def extract_fields(raw_text: str, script_type: ScriptType | None = None) -> FieldReadings:
    """Drop-in replacement for shasan_stub.extract_fields: takes the raw
    OCR text only, sends it to Qwen2.5 via Ollama, and returns one
    FieldReading per FieldName. Never raises — any failure (Ollama down,
    bad response, unparseable JSON) is logged and results in an all-empty
    FieldReadings so the pipeline's existing Gemini gap-fill and
    "queued for manual entry" behavior takes over exactly as it already
    does for any other low-confidence/missing field.

    `script_type` is optional (pipeline.py always passes it; kept optional
    here so this stays a safe drop-in for any other caller) and enables an
    immediate self-check: if mutawalli_name or village comes back pure
    Latin script for a non-Latin document, that's the same
    auto-transliteration failure mode covered in base.looks_transliterated
    — rather than silently accepting it, this fires ONE corrective retry
    against the same OCR text asking Qwen to copy the original script
    instead. If the retry succeeds, the corrected value is used (at a
    slightly reduced confidence, since it took a second attempt). If it
    doesn't, the original (still-suspect) reading is kept as-is and left
    for pipeline.py's post-gap-fill guard to catch as a last resort."""
    text = (raw_text or "").strip()
    if not text:
        logger.warning("qwen_mapper.extract_fields called with empty OCR text — skipping Ollama call.")
        return _empty_readings()

    response_text = _call_ollama(text)
    if response_text is None:
        return _empty_readings()

    parsed = _parse_json(response_text)
    if parsed is None:
        return _empty_readings()

    readings = _to_field_readings(parsed)

    if script_type is not None and script_type != ScriptType.english_latin:
        for field in SCRIPT_SENSITIVE_FIELDS:
            reading = readings.get(field)
            if reading is None or not reading.value:
                continue
            if not looks_transliterated(reading.value, script_type):
                continue
            logger.info("Qwen returned a Latin-script value for %s ('%s') on a %s document — retrying.",
                        field.value, reading.value, script_type.value)
            corrected = _retry_native_script_field(text, field, reading.value)
            if corrected and not looks_transliterated(corrected, script_type):
                readings[field] = FieldReading(
                    value=corrected, confidence=PRESENT_CONFIDENCE - 0.10, source=ExtractionSource.qwen_slm
                )
            else:
                # Retry didn't fix it either — drop confidence below
                # GAP_FILL_THRESHOLD so pipeline.py's Gemini gap-fill gets
                # an independent (vision-based) attempt at this field
                # rather than the transliterated guess sitting untouched
                # at Qwen's normal 0.90. If Gemini's attempt also comes
                # back transliterated, pipeline.py's post-gap-fill guard
                # is the final safety net.
                reading.confidence = min(reading.confidence, 0.35)

    return readings
