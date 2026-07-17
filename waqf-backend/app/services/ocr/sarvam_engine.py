"""
Sarvam Vision 3B adapter — primary OCR engine per the project doc, and the
best available option for Urdu Nastaliq specifically. Covers five scripts
in this pipeline: Urdu Nastaliq, Marathi/Hindi/Sanskrit Devanagari, and
English/Latin.

Calls the Sarvam Vision API directly from this backend process via the
official `sarvamai` SDK's async Document Intelligence job flow (create job
-> upload file -> start -> wait_until_complete -> download output), per
https://docs.sarvam.ai/api-reference-docs/getting-started/models/sarvam-vision.
Everything runs inside this one FastAPI process/machine — there is no
separate OCR microservice or second machine involved. (An earlier revision
of this file called out over HTTP to a second laptop on the LAN at
`http://192.168.1.40:8000/ocr` — that's been removed; this is back to a
plain in-process Python function call.)

The SDK call is synchronous/blocking (wait_until_complete polls internally),
so this runs in a worker thread from the pipeline to avoid blocking the
event loop — see services/ocr/pipeline.py.

Everything here is defensive: a missing SDK, a missing/invalid API key, an
unsupported file, or a network error (to Sarvam's own API, not a local
microservice) all degrade to a `RawTextResult` with `error` set rather than
raising, so the pipeline can fall back to Tesseract or GPT-4o mini without
the request failing outright.
"""
from __future__ import annotations

import html
import logging
import re
import tempfile
import zipfile
from pathlib import Path

from app.config import get_settings
from app.models import ExtractionSource, ScriptType
from .base import RawTextResult
from .tesseract_engine import ARABIC_RANGES, DEVANAGARI_RANGE

logger = logging.getLogger(__name__)
settings = get_settings()

# Sarvam Vision language codes for the five scripts in scope (Urdu
# Nastaliq, Marathi Devanagari, Hindi Devanagari, Sanskrit Devanagari, and
# English/Latin). All five are confirmed-supported BCP-47 codes per
# https://docs.sarvam.ai/api-reference-docs/document-intelligence.
SCRIPT_TO_LANGUAGE = {
    ScriptType.urdu_nastaliq: "ur-IN",
    ScriptType.marathi_devanagari: "mr-IN",
    ScriptType.hindi_devanagari: "hi-IN",
    ScriptType.sanskrit_devanagari: "sa-IN",
    ScriptType.english_latin: "en-IN",
}

# Known limitation: if the caller has no script hint at all (e.g. a PDF with
# no installed Tesseract language packs and a filename that doesn't say
# which script it is), this requests Hindi from the API by default — the
# same default Sarvam's own API uses for an omitted language, and the same
# default `tesseract_engine._classify_devanagari` falls back to for
# zero-evidence Devanagari text. This can still reduce read quality on an
# actual Urdu/Marathi/Sanskrit document even though the pipeline's final
# `scriptType` label is corrected afterward from whatever text comes back
# (see pipeline.py:_final_script). Install the Tesseract urd/mar/hin/san
# language packs (see README) to get a reliable hint before this call, or
# pass a script-indicating filename, to avoid the mismatch.

MAX_JOB_WAIT_SECONDS = 25  # keeps the Wk-12 "<30s" demo-gate target in reach


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_markup(text: str) -> str:
    """Sarvam renders complex tables as raw HTML *inside* the ".md" output
    (and the ".html" fallback is obviously all markup too), so plain-text
    tag stripping is needed either way. Without this, tag fragments like
    "</td>" end up being read as a field's value by the label/regex
    extraction pass in shasan_stub.py, since it just scans raw text lines."""
    unescaped = html.unescape(text)
    no_tags = _TAG_RE.sub(" ", unescaped)
    # Collapse the runs of whitespace tag-stripping tends to leave behind,
    # but keep line breaks so the line-based label lookup still works.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in no_tags.splitlines()]
    return "\n".join(line for line in lines if line)


LANGUAGE_EXPECTED_SCRIPT = {
    "ur-IN": "arabic",
    "mr-IN": "devanagari",
    "hi-IN": "devanagari",
    "sa-IN": "devanagari",
    "en-IN": "latin",
}


def _script_ratio(text: str, script: str) -> float:
    """Fraction of alphabetic characters in `text` that fall in the given
    script's Unicode block(s) — a proxy for "did we actually get the
    language we asked for back?"."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    if script == "arabic":
        hits = sum(1 for ch in letters if any(lo <= ord(ch) <= hi for lo, hi in ARABIC_RANGES))
    elif script == "devanagari":
        hits = sum(1 for ch in letters if DEVANAGARI_RANGE[0] <= ord(ch) <= DEVANAGARI_RANGE[1])
    else:  # latin
        hits = sum(1 for ch in letters if ch.isascii())
    return hits / len(letters)


def _derive_confidence(text: str, language: str, status) -> float:
    """Sarvam Vision's job-status response doesn't include a per-word or
    per-page read-confidence score — only `page_metrics` pass/fail counts
    (see https://docs.sarvam.ai/api-reference-docs/document-intelligence,
    "Response Format"). There is no single scalar to read off the API the
    way Tesseract exposes per-word confidences, so a flat constant here
    was never actually measuring anything about *this* read.

    This combines the real signals Sarvam does give us into a proxy:
      - page success ratio from `page_metrics` (a job can complete with
        some pages failed, which a job_state check alone won't catch)
      - how much of the returned text is actually in the script we asked
        for — a "successful" job that comes back mostly Latin/garbled for
        a requested Urdu/Devanagari read is a real quality problem
        page_metrics won't flag on its own
      - a mild length sanity check, since a one-word "read" of a full page
        scan is a red flag regardless of what script it's in

    This is a heuristic proxy standing in for a read-confidence Sarvam
    doesn't expose — not a reproduction of an internal Sarvam score."""
    page_metrics = getattr(status, "page_metrics", None)
    if page_metrics is not None:
        total = getattr(page_metrics, "total_pages", None) or getattr(page_metrics, "pages_processed", None)
        succeeded = getattr(page_metrics, "pages_succeeded", None)
        page_ratio = (succeeded / total) if total and succeeded is not None else 1.0
        page_ratio = max(0.0, min(1.0, page_ratio))
    else:
        page_ratio = 1.0  # metrics unavailable (e.g. mocked client in tests) — don't penalize

    expected_script = LANGUAGE_EXPECTED_SCRIPT.get(language, "devanagari")
    script_ratio = _script_ratio(text, expected_script)
    length_factor = 1.0 if len(text) >= 40 else max(0.5, len(text) / 40)

    # Weighted toward script match — the strongest signal that this is a
    # usable read in the right language rather than noise or a wrong-script
    # misfire; page success and length are secondary sanity checks.
    confidence = 0.55 * script_ratio + 0.30 * page_ratio + 0.15 * length_factor
    return round(max(0.0, min(0.98, confidence)), 4)


def _extract_text_from_output_zip(zip_path: Path) -> str:
    """The job output is a ZIP of per-page Markdown/HTML plus a JSON
    structured payload. We only need plain text for field extraction, so
    concatenate every .md (preferred) or .html file inside."""
    texts: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        md_names = [n for n in names if n.lower().endswith(".md")]
        target_names = md_names or [n for n in names if n.lower().endswith((".html", ".htm"))]
        for name in target_names:
            with zf.open(name) as f:
                texts.append(f.read().decode("utf-8", errors="ignore"))
    return _strip_markup("\n\n".join(texts).strip())


def run_sarvam_vision(raw_bytes: bytes, filename: str, script_hint: ScriptType | None) -> RawTextResult:
    if not settings.sarvam_configured:
        return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0,
                              error="Sarvam API key not configured")

    try:
        from sarvamai import SarvamAI
    except ImportError:
        return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0,
                              error="sarvamai SDK not installed")

    language = SCRIPT_TO_LANGUAGE.get(script_hint, "hi-IN")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_input = Path(tmpdir) / (filename or "scan.png")
        tmp_input.write_bytes(raw_bytes)
        tmp_output_zip = Path(tmpdir) / "output.zip"

        try:
            client = SarvamAI(api_subscription_key=settings.sarvam_api_key)
            job = client.document_intelligence.create_job(language=language, output_format="md")
            job.upload_file(str(tmp_input))
            job.start()
            status = job.wait_until_complete(timeout=MAX_JOB_WAIT_SECONDS)

            job_state = getattr(status, "job_state", None) or getattr(status, "status", None)
            if job_state and str(job_state).lower() not in ("completed", "success", "succeeded"):
                return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0,
                                      error=f"Sarvam job finished with state={job_state}")

            job.download_output(str(tmp_output_zip))
            text = _extract_text_from_output_zip(tmp_output_zip)

            if not text:
                return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0,
                                      error="Sarvam job completed but returned no extractable text")

            confidence = _derive_confidence(text, language, status)
            return RawTextResult(text=text, engine=ExtractionSource.sarvam_vision, confidence=confidence)

        except TimeoutError:
            return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0,
                                  error=f"Sarvam job did not complete within {MAX_JOB_WAIT_SECONDS}s")
        except Exception as exc:
            logger.warning("Sarvam Vision call failed: %s", exc)
            return RawTextResult(text="", engine=ExtractionSource.sarvam_vision, confidence=0.0, error=str(exc))
