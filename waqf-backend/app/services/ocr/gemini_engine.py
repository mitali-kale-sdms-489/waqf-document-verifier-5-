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
import re
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


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_UNESCAPED_QUOTE_RE = re.compile(r'(?<!\\)"')


def _repair_truncated_json(text: str) -> str:
    """Best-effort repair for a response that got cut off mid-generation
    (finishReason=MAX_TOKENS, or the connection/stream ending early) —
    e.g. '{"village": "Mauje Bahadurpur"' with no closing brace. This is a
    genuinely incomplete response, not malformed JSON, so no amount of
    strict=False or delimiter-fixing helps; the only thing that can save
    it is closing whatever was left open:
      1. If the text ends mid-string (an odd number of unescaped quotes),
         close that string.
      2. Append enough closing braces to balance every '{' that was
         opened but never closed.
    This can't recover a field that was cut off before its closing quote
    even started, or one truncated mid-key — those simply come back as
    whatever partial garbage was captured, which is an acceptable
    trade-off since the alternative is losing every field in the response,
    including the ones that completed fine before the cutoff."""
    text = text.rstrip()
    if _UNESCAPED_QUOTE_RE.findall(text) and len(_UNESCAPED_QUOTE_RE.findall(text)) % 2 == 1:
        text += '"'
    # Strip a trailing comma left dangling by a cutoff right after a
    # completed "key": "value" pair (the common truncation point) — a
    # trailing comma before the closing brace we're about to add makes
    # the "repaired" text still invalid JSON otherwise.
    text = text.rstrip()
    if text.endswith(","):
        text = text[:-1]
    open_braces = text.count("{") - text.count("}")
    if open_braces > 0:
        text += "}" * open_braces
    return text


def _parse_translation_json(content: str) -> dict | None:
    """Parses the translation call's response body, tolerating the ways
    Gemini's JSON mode still occasionally goes wrong on mixed-script text.

    Tried in order:
    1. A normal strict parse (the common case).
    2. strict=False: Python's json module rejects raw control characters
       (a literal newline, tab, etc.) inside a string value by default,
       which is exactly the "Expecting ',' delimiter" error this was
       thrown for — Gemini sometimes emits an unescaped newline inside a
       transliterated value instead of the required `\\n`. strict=False
       allows those control characters through instead of failing the
       whole parse over one stray character.
    3. Extracting the first {...} block and retrying both of the above,
       in case the model wrapped the JSON in markdown fences or added
       stray commentary despite the prompt saying not to.
    4. Truncation repair: if the response was cut off mid-generation
       (missing closing brace/quote), try closing it and parsing again —
       recovers every field that finished before the cutoff instead of
       losing the whole response over the one that didn't.

    Returns None (with the raw content logged) only if every attempt
    fails, so the actual malformed text is visible in the logs instead of
    just the exception message."""
    candidates = [content]
    match = _JSON_OBJECT_RE.search(content)
    if match and match.group(0) != content:
        candidates.append(match.group(0))

    for text in candidates:
        for strict in (True, False):
            try:
                parsed = json.loads(text, strict=strict)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                continue

    repaired = _repair_truncated_json(content)
    if repaired != content:
        try:
            parsed = json.loads(repaired, strict=False)
            if isinstance(parsed, dict):
                logger.info("Recovered a truncated Gemini translation response via brace/quote repair.")
                return parsed
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse Gemini translation response after repair attempts. Raw content: %r",
                    content[:1000])
    return None


TRANSLATION_PROMPT = """You are helping an English-speaking reviewer read Waqf (Islamic endowment) property \
registration fields that were transcribed in their original script (Urdu Nastaliq, or Devanagari — Marathi, \
Hindi, or Sanskrit).

For each field value below, give its English rendering:
- For a person's name or a place name (mutawalli_name, village): give a TRANSLITERATION — how the name reads \
aloud in English/Latin letters (e.g. "حاجی محمد رفیق" -> "Haji Muhammad Rafiq"), NOT a meaning-based \
translation. Use common, natural English spellings for Muslim/South Asian names rather than a rigid \
letter-by-letter romanization.
- For property_id: convert any Urdu-Indic or Devanagari digits to plain Western (0-9) digits; if the value \
is already in Western digits/Latin letters, return it unchanged.
- For extent: convert any non-Latin digits to Western digits and transliterate the unit word (e.g. "کنال" \
-> "kanal", "مرلہ" -> "marla") rather than translating it to a different unit.

Respond with ONLY a JSON object, no prose, no markdown fences, whose keys are exactly the field names given \
below (only include keys for fields provided) and whose values are the English rendering as a string. If a \
provided value cannot be confidently rendered in English, return null for that key rather than guessing.

FIELDS:
{fields_json}
"""

# Gemini's translation pass is restricted to these four fields. Excludes
# survey_number and registration_date deliberately: both are already
# plain digits/an ISO-ish date in the vast majority of scans (registration
# numbers and dates are essentially never written with name-like script
# ambiguity the way mutawalli_name/village are), so a full Gemini vision-
# quality transliteration call added no real value for them — the local,
# free, offline `convert_indic_digits` fallback further down in
# pipeline.py already covers the only thing they actually need (Indic ->
# Western digit conversion). Keeping them out of every translation call
# cuts the Gemini call's field count (smaller prompt/response) and, more
# importantly, means a document with weak survey_number/registration_date
# readings doesn't need this call to succeed at all.
TRANSLATABLE_FIELDS = {FieldName.mutawalli_name, FieldName.village, FieldName.property_id, FieldName.extent}


def run_gemini_translation(fields: FieldReadings) -> dict[FieldName, str] | None:
    """Best-effort English transliteration/translation pass over whatever
    field values were extracted, run as a separate text-only Gemini call
    (see pipeline.py, called after mapping + gap-fill). Returns None (not
    an empty dict) when the call fails or isn't configured, so pipeline.py
    can tell "translation didn't run" apart from "ran and had nothing to
    translate" — same convention as run_gemini_field_extraction above.
    Never raises."""
    present = {f.value: r.value for f, r in fields.items() if r.value and f in TRANSLATABLE_FIELDS}
    if not present:
        return None
    if not settings.gemini_configured:
        return None

    prompt = TRANSLATION_PROMPT.format(fields_json=json.dumps(present, ensure_ascii=False, indent=2))
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            # Observed in practice: finishReason=MAX_TOKENS with well under
            # 100 tokens of actual JSON output — gemini-flash-latest
            # appears to be a reasoning/"thinking" model that spends part
            # of maxOutputTokens on invisible internal reasoning before
            # writing the visible answer, and harder scripts (Sanskrit)
            # seem to push that reasoning longer, leaving less budget for
            # the real output. thinkingBudget=0 asks it to skip that
            # reasoning entirely, which this call doesn't need anyway —
            # it's a small, deterministic transliteration/digit-conversion
            # task, not something that benefits from step-by-step
            # reasoning. maxOutputTokens is also raised well past what the
            # visible JSON alone needs, as a second line of defense in
            # case thinkingBudget isn't honored by whatever model
            # "-latest" currently resolves to.
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    data = _post_generate_content(body)
    if not data:
        return None

    finish_reason = None
    try:
        finish_reason = data["candidates"][0].get("finishReason")
    except (KeyError, IndexError, TypeError):
        pass
    if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        logger.warning("Gemini translation call finished with reason=%s (response may be truncated/blocked).",
                        finish_reason)

    content = _extract_text(data)
    if content is None:
        logger.warning("Unexpected Gemini response shape for translation")
        return None
    parsed = _parse_translation_json(content)
    if parsed is None:
        return None

    result: dict[FieldName, str] = {}
    for field in fields:
        if field not in TRANSLATABLE_FIELDS:
            continue
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
