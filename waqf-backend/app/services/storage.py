"""
File storage for uploaded scans.

Local disk is the default and always works. S3 is used only when
`settings.s3_configured` is True (see app/config.py — this is False while
AWS_SECRET_ACCESS_KEY is the placeholder value, which is the case out of the
box for this handoff). storage_path on WaqfDocument encodes which backend
owns the file:
  - local path, e.g. "storage/uploads/doc-abc123_scan.tiff"
  - "s3://<bucket>/<key>" when S3 is configured

Segment 4 (admin) can add a migration/backfill between the two later; not
needed for the POC demo.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.config import get_settings

settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # waqf-backend/
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(document_id: str, original_filename: str) -> str:
    """Prevents path traversal / collisions while keeping the extension."""
    ext = Path(original_filename).suffix.lower()
    ext = ext if ext and len(ext) <= 8 else ""
    return f"{document_id}{ext}"


def _s3_client():
    import boto3  # local import: keeps boto3 optional at app-startup time

    return boto3.client(
        "s3",
        region_name=settings.aws_s3_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def save_upload(document_id: str, file: UploadFile, raw_bytes: bytes) -> str:
    """Persists the already-read file bytes and returns the storage_path to
    store on WaqfDocument. Caller reads raw_bytes once (for size validation)
    and passes them here so we don't re-read the SpooledTemporaryFile twice.
    """
    filename = _safe_filename(document_id, file.filename or f"{uuid.uuid4().hex}.bin")

    if settings.s3_configured:
        key = f"uploads/{filename}"
        try:
            client = _s3_client()
            client.put_object(
                Bucket=settings.aws_s3_bucket,
                Key=key,
                Body=raw_bytes,
                ContentType=file.content_type or "application/octet-stream",
            )
            return f"s3://{settings.aws_s3_bucket}/{key}"
        except Exception:
            # Fall through to local disk — a demo should never hard-fail an
            # upload because of an optional storage backend.
            pass

    dest = UPLOAD_DIR / filename
    with open(dest, "wb") as f:
        f.write(raw_bytes)
    return str(dest.relative_to(BASE_DIR))


def load_file_response(storage_path: str, mime_type: str | None, filename: str):
    """Returns a FastAPI response (FileResponse for local disk, streamed
    bytes for S3) suitable for returning directly from a route."""
    media_type = mime_type or "application/octet-stream"

    if storage_path.startswith("s3://"):
        _, _, rest = storage_path.partition("s3://")
        bucket, _, key = rest.partition("/")
        client = _s3_client()
        obj = client.get_object(Bucket=bucket, Key=key)
        return StreamingResponse(
            obj["Body"].iter_chunks(),
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    local_path = BASE_DIR / storage_path
    if not local_path.exists():
        raise FileNotFoundError(storage_path)
    # Starlette's FileResponse defaults content_disposition_type to
    # "attachment" whenever `filename` is set, which tells the browser to
    # download the file rather than render it — this is what was causing the
    # preview <img>/<iframe> to come back blank and the "preview" click to
    # trigger a download instead. "inline" lets the browser render it and
    # still keeps the filename around if the user does explicitly save it.
    return FileResponse(local_path, media_type=media_type, filename=filename, content_disposition_type="inline")


def load_bytes(storage_path: str) -> bytes:
    """Raw bytes for a stored file — used by the OCR pipeline, which needs
    the actual image/PDF content regardless of backend."""
    if storage_path.startswith("s3://"):
        _, _, rest = storage_path.partition("s3://")
        bucket, _, key = rest.partition("/")
        client = _s3_client()
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

    local_path = BASE_DIR / storage_path
    return local_path.read_bytes()
