"""
Text translation for reviewer-facing free text (currently: the supervisor's
flag/reject reason shown on the Dashboard's "Flagged for review" dialog).

Previously called Sarvam AI's Text -> Translate endpoint. Now calls a
locally-running Ollama server instead (the same one app/services/ocr/
qwen_mapper.py already uses for field-extraction), via a plain translation
prompt against settings.ollama_model. This means:

  - No API key needed, no per-call cost.
  - If Ollama itself runs on a different machine than the backend (e.g. your
    own laptop while the backend is deployed elsewhere), just point
    OLLAMA_URL at an ngrok URL forwarding to it — e.g.
    `ngrok http 11434` on the machine running Ollama, then set
    OLLAMA_URL=https://<your-subdomain>.ngrok-free.app in .env. Nothing in
    this file changes either way; it always just calls settings.ollama_url.

Kept defensive like qwen_mapper.py / the old sarvam version: a missing/
unreachable Ollama server, a timeout, or a malformed response all degrade
to a raised TranslationError with a human-readable message rather than an
unhandled exception, so the router can turn it into a clean 502 instead of
a 500 stack trace.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT = settings.ollama_timeout_seconds  # configurable via OLLAMA_TIMEOUT_SECONDS; see config.py


class TranslationError(Exception):
    """Raised for any translation failure the caller should see a message for."""


# Languages a reviewer can translate a flag reason into. `code` is kept in
# the same BCP-47-ish shape the frontend already expects (src/api/documents.ts,
# Dashboard.tsx language picker); `label` is both what shows in the UI and
# what gets dropped into the Ollama prompt below, since a local text model
# has no separate "language code" concept the way Sarvam's API did.
SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": "en-IN", "label": "English"},
    {"code": "hi-IN", "label": "Hindi"},
    {"code": "mr-IN", "label": "Marathi"},
    {"code": "sa-IN", "label": "Sanskrit"},
    {"code": "ur-IN", "label": "Urdu"},
]

_LANGUAGE_LABELS = {lang["code"]: lang["label"] for lang in SUPPORTED_LANGUAGES}

_PROMPT_TEMPLATE = """Translate the text below into {target_label}.

Rules:
- Respond with ONLY the translated text.
- Do not add quotes, notes, explanations, or the original text.
- Preserve the original meaning and tone as closely as possible.

TEXT:

{text}
"""


def _call_ollama(prompt: str) -> str | None:
    """POSTs to Ollama's /api/generate and returns the raw model output
    string, or None if the call failed for any reason (connection refused,
    timeout, non-2xx, malformed response body)."""
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
    return response_text.strip()


def translate_text(text: str, target_language_code: str, source_language_code: str = "auto") -> str:
    """Translates `text` into `target_language_code` (e.g. "en-IN", "ur-IN").

    source_language_code is accepted for compatibility with the router's
    call signature, but unused here — the model is simply asked to
    translate into the target language and left to detect the source
    language itself, the same "auto" behaviour the old Sarvam call had.
    Raises TranslationError on any failure.
    """
    if not text or not text.strip():
        raise TranslationError("There is no text to translate.")
    target_label = _LANGUAGE_LABELS.get(target_language_code)
    if target_label is None:
        raise TranslationError(f"Unsupported target language: {target_language_code}")

    prompt = _PROMPT_TEMPLATE.format(target_label=target_label, text=text[:2000])
    translated = _call_ollama(prompt)
    if translated is None:
        raise TranslationError(
            "Translation failed. Is Ollama running and reachable at the configured OLLAMA_URL "
            "(see .env — this can be a local address or an ngrok URL)?"
        )
    return translated
