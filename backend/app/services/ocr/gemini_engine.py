"""
Gemini Vision adapter — replaces GPT-4o mini as the fallback OCR/extraction
engine (GPT-4o mini calls were failing in practice, see handoff notes).

Uses plain HTTPS calls to the Gemini API's generateContent endpoint via
httpx, the same lightweight-dependency approach the old openai_engine.py
used, rather than pulling in the `google-generativeai` SDK.

Model name: Google renames/retires Gemini model IDs fairly often (e.g.
gemini-2.0-flash was shut down June 2026). `gemini_model` defaults to the
"gemini-flash-latest" alias, which Google keeps pointed at whatever their
current-generation Flash model is, specifically so this doesn't need a code
change every time a dated model ID is deprecated. Override via the
GEMINI_MODEL env var if you want to pin a specific version instead.

Three entry points, the first two mirroring the old GPT-4o mini adapter's shape so
pipeline.py's call sites barely changed:
  - run_gemini_ocr: raw page transcription, used as a fallback when Sarvam
    Vision's own confidence is low (see pipeline.py).
  - run_gemini_field_extraction: vision + JSON-schema prompt that reads the
    scan directly and returns the six Waqf record fields, used to backfill
    low-confidence fields the Shasan-SLM stub's regex pass couldn't resolve.
  - run_gemini_translation: text-only pass over the final extracted field
    values that returns an English transliteration/rendering of each,
    used by pipeline.py to populate FieldReading.value_en for the review UI.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time

import httpx

from app.config import get_settings
from app.models import ExtractionSource, FieldName
from .base import FieldReading, FieldReadings, RawTextResult

logger = logging.getLogger(__name__)
settings = get_settings()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 25.0

# Serializes + throttles every Gemini call this process makes, so a
# document that needs OCR fallback, gap-fill, AND translation (up to 3
# Gemini calls) doesn't burst them back-to-back and blow straight through
# a free-tier requests-per-minute quota. `_last_call_at` is process-wide
# (not per-document) since the quota itself is process/key-wide.
_call_lock = threading.Lock()
_last_call_at: float = 0.0


def _throttle() -> None:
    global _last_call_at
    with _call_lock:
        wait = settings.gemini_min_call_interval_seconds - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _post_generate_content(body: dict) -> dict | None:
    """POSTs `body` to the configured Gemini model's generateContent
    endpoint, shared by every call site below (OCR, field extraction,
    translation) so throttling and retry behavior only need to live in one
    place. Retries on HTTP 429 up to `gemini_max_retries` times, honoring
    the response's Retry-After header when present and falling back to
    exponential backoff otherwise. Any other failure (timeout, other
    4xx/5xx, connection error) is NOT retried — logged and treated as
    "Gemini unavailable for this call", same as before. Never raises."""
    if not settings.gemini_configured:
        return None

    url = f"{GEMINI_API_BASE}/{settings.gemini_model}:generateContent"
    attempt = 0
    while True:
        _throttle()
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(url, params={"key": settings.gemini_api_key}, json=body)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < settings.gemini_max_retries:
                retry_after_header = exc.response.headers.get("Retry-After")
                try:
                    delay = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    delay = None
                if delay is None:
                    delay = settings.gemini_min_call_interval_seconds * (2**attempt)
                attempt += 1
                logger.warning(
                    "Gemini (%s) rate-limited (429) — retrying in %.1fs (attempt %d/%d).",
                    settings.gemini_model, delay, attempt, settings.gemini_max_retries,
                )
                time.sleep(delay)
                continue
            logger.warning("Gemini (%s) call failed: %s", settings.gemini_model, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - any other transport/parse failure must not crash the pipeline
            logger.warning("Gemini (%s) call failed: %s", settings.gemini_model, exc)
            return None


FIELD_EXTRACTION_PROMPT = """You are transcribing a scanned Waqf (Islamic endowment) property registration \
record, written in Urdu (Nastaliq script), Marathi, Hindi, or Sanskrit (all Devanagari script), or English. \
Read the document image and extract these six fields. Respond with ONLY a JSON object, no prose, no \
markdown fences, with exactly these keys:

{
  "property_id": string or null,
  "mutawalli_name": string or null,
  "survey_number": string or null,
  "registration_date": string or null (ISO format YYYY-MM-DD if determinable, otherwise as written),
  "extent": string or null (area, keep original unit e.g. "0.82 ha"),
  "village": string or null,
  "confidence": object mapping each of the above keys to a number from 0 to 1 representing how certain \
you are of that specific reading
}

If a field is illegible or absent, use null for its value and a low confidence (below 0.3) for it. \
Preserve the original script (Urdu Nastaliq, Devanagari, or Latin) in name/place fields rather than \
transliterating. Devanagari text may be Marathi, Hindi, or Sanskrit — transcribe exactly as written \
without translating between them."""


def _generate_content(raw_bytes: bytes, mime_type: str | None, prompt: str, *, json_response: bool) -> dict | None:
    mime = mime_type if mime_type and (mime_type.startswith("image/") or mime_type == "application/pdf") else "image/png"
    b64 = base64.b64encode(raw_bytes).decode("ascii")

    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            **({"responseMimeType": "application/json"} if json_response else {}),
        },
    }
    return _post_generate_content(body)


def _extract_text(data: dict) -> str | None:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


def run_gemini_ocr(raw_bytes: bytes, mime_type: str | None) -> RawTextResult:
    prompt = (
        "Transcribe every line of text visible in this scanned document image exactly as written, "
        "preserving line breaks. The document may be in Urdu (Nastaliq), Marathi/Hindi/Sanskrit "
        "(Devanagari), or English. Output only the transcription, no commentary."
    )
    data = _generate_content(raw_bytes, mime_type, prompt, json_response=False)
    if not data:
        return RawTextResult(text="", engine=ExtractionSource.gemini_vision, confidence=0.0,
                              error="Gemini OCR call failed or not configured")
    text = _extract_text(data)
    if text is None:
        return RawTextResult(text="", engine=ExtractionSource.gemini_vision, confidence=0.0,
                              error="Unexpected Gemini response shape")
    text = text.strip()
    return RawTextResult(text=text, engine=ExtractionSource.gemini_vision, confidence=0.7 if text else 0.0)


TRANSLATION_PROMPT = """You are helping an English-speaking reviewer read Waqf (Islamic endowment) property \
registration fields that were transcribed in their original script (Urdu Nastaliq, or Devanagari — Marathi, \
Hindi, or Sanskrit).

For each field value below, give its English rendering:
- For a person's name or a place name (mutawalli_name, village): give a TRANSLITERATION — how the name reads \
aloud in English/Latin letters (e.g. "حاجی محمد رفیق" -> "Haji Muhammad Rafiq"), NOT a meaning-based \
translation. Use common, natural English spellings for Muslim/South Asian names rather than a rigid \
letter-by-letter romanization.
- For property_id and survey_number: convert any Urdu-Indic or Devanagari digits to plain Western (0-9) \
digits; if the value is already in Western digits/Latin letters, return it unchanged.
- For registration_date: return it unchanged if already ISO (YYYY-MM-DD) or otherwise render any non-Latin \
digits as Western digits.
- For extent: convert any non-Latin digits to Western digits and transliterate the unit word (e.g. "کنال" \
-> "kanal", "مرلہ" -> "marla") rather than translating it to a different unit.

Respond with ONLY a JSON object, no prose, no markdown fences, whose keys are exactly the field names given \
below (only include keys for fields provided) and whose values are the English rendering as a string. If a \
provided value cannot be confidently rendered in English, return null for that key rather than guessing.

FIELDS:
{fields_json}
"""


def run_gemini_translation(fields: FieldReadings) -> dict[FieldName, str] | None:
    """Best-effort English transliteration/translation pass over whatever
    field values were extracted, run as a separate text-only Gemini call
    (see pipeline.py, called after mapping + gap-fill). Returns None (not
    an empty dict) when the call fails or isn't configured, so pipeline.py
    can tell "translation didn't run" apart from "ran and had nothing to
    translate" — same convention as run_gemini_field_extraction above.
    Never raises."""
    present = {f.value: r.value for f, r in fields.items() if r.value}
    if not present:
        return None
    if not settings.gemini_configured:
        return None

    prompt = TRANSLATION_PROMPT.format(fields_json=json.dumps(present, ensure_ascii=False, indent=2))
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    data = _post_generate_content(body)
    if not data:
        return None

    content = _extract_text(data)
    if content is None:
        logger.warning("Unexpected Gemini response shape for translation")
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse Gemini translation response: %s", exc)
        return None
    if not isinstance(parsed, dict):
        return None

    result: dict[FieldName, str] = {}
    for field in fields:
        value = parsed.get(field.value)
        if isinstance(value, str) and value.strip():
            result[field] = value.strip()
    return result


def run_gemini_field_extraction(raw_bytes: bytes, mime_type: str | None) -> FieldReadings | None:
    """Returns None (not a low-confidence FieldReadings) when the call fails
    or isn't configured, so pipeline.py can tell "Gemini ran and found
    nothing" apart from "Gemini didn't run at all"."""
    data = _generate_content(raw_bytes, mime_type, FIELD_EXTRACTION_PROMPT, json_response=True)
    if not data:
        return None
    content = _extract_text(data)
    if content is None:
        logger.warning("Unexpected Gemini response shape for field extraction")
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse Gemini field extraction response: %s", exc)
        return None

    confidences = parsed.get("confidence", {}) if isinstance(parsed.get("confidence"), dict) else {}
    readings: FieldReadings = {}
    for field in FieldName:
        value = parsed.get(field.value)
        value = value if isinstance(value, str) and value.strip() else None
        conf = confidences.get(field.value)
        conf = float(conf) if isinstance(conf, (int, float)) else (0.6 if value else 0.2)
        readings[field] = FieldReading(value=value, confidence=max(0.0, min(1.0, conf)),
                                        source=ExtractionSource.gemini_vision)
    return readings
