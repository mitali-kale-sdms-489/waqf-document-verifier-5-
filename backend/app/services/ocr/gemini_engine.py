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

Two entry points, mirroring the old GPT-4o mini adapter's shape so
pipeline.py's call sites barely changed:
  - run_gemini_ocr: raw page transcription, used as a fallback when Sarvam
    Vision's own confidence is low (see pipeline.py).
  - run_gemini_field_extraction: vision + JSON-schema prompt that reads the
    scan directly and returns the six Waqf record fields, used to backfill
    low-confidence fields the Shasan-SLM stub's regex pass couldn't resolve.
"""
from __future__ import annotations

import base64
import json
import logging

import httpx

from app.config import get_settings
from app.models import ExtractionSource, FieldName
from .base import FieldReading, FieldReadings, RawTextResult

logger = logging.getLogger(__name__)
settings = get_settings()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 25.0

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
    if not settings.gemini_configured:
        return None

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

    url = f"{GEMINI_API_BASE}/{settings.gemini_model}:generateContent"

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Gemini (%s) call failed: %s", settings.gemini_model, exc)
        return None


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
