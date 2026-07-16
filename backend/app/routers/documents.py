"""
Document endpoints for Segment 2: upload (+ real OCR pipeline), queue, list,
get-by-id, and file preview streaming.

Route shapes intentionally mirror the frontend's mock API comments in
src/data/mockDocuments.ts 1:1 (GET /documents/queue, GET /documents/{id},
GET /documents, POST /documents/upload) so Segment 3/4 and the frontend
integration are a straight swap from mocks to real calls.

Validation rules (mandatory_fields_present, survey_number_format,
date_plausibility, cross_document_consistency — Segment 3's engine, see
app/services/validation.py) run right after the OCR pipeline persists
extracted fields, and again after a reviewer submits corrections since
those can change which rules pass. A document therefore leaves upload with
status="validated" (not "extracted") once at least one field was
extracted, and its validations list already populated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_user_flexible
from app.models import (
    DocumentStatus,
    DpdpStatus,
    ExtractedField,
    ExtractionSource,
    FieldCorrection,
    OcrSettings,
    Review,
    ReviewAction,
    ScriptType,
    User,
    WaqfDocument,
)
from app.schemas_documents import (
    DashboardStatsOut,
    DocumentDetailOut,
    ReviewOut,
    ReviewSubmitIn,
    UploadDiagnostics,
    UploadResponse,
    ValidationResultOut,
    WaqfDocumentOut,
)
from app.models import ValidationResult
from app.services import dpdp, storage, validation
from app.services.ocr import pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

ACCEPTED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/tiff", "application/pdf"}
ACCEPTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".pdf")
MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB — matches Upload.tsx


def _is_accepted_file(filename: str, content_type: str | None) -> bool:
    if content_type in ACCEPTED_MIME_TYPES:
        return True
    return filename.lower().endswith(ACCEPTED_EXTENSIONS)


def _preview_url(document_id: str, request_token: str) -> str:
    return f"/api/v1/documents/{document_id}/file?token={request_token}"


def _to_out(document: WaqfDocument, preview_token: str | None = None) -> WaqfDocumentOut:
    out = WaqfDocumentOut.model_validate(document)
    if preview_token:
        out.preview_url = _preview_url(document.id, preview_token)
    return out


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not file.filename or not _is_accepted_file(file.filename, file.content_type):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Unsupported file type. Use JPG, PNG, TIFF, WEBP, or PDF.",
        )

    raw_bytes = file.file.read()
    if len(raw_bytes) > MAX_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is larger than the 25 MB limit.")
    if len(raw_bytes) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")

    dpdp_status, dpdp_reason = dpdp.check_dpdp_compliance(file.filename)
    document = WaqfDocument(
        filename=file.filename,
        status=DocumentStatus.processing,
        # script_type is NOT NULL; this is a provisional value, overwritten
        # below once the OCR pipeline detects the real one.
        script_type=ScriptType.marathi_devanagari,
        # A document counts as synthetic iff its filename matched the same
        # synthetic/sample/demo/template/test naming convention the DPDP
        # check already looks for (see app/services/dpdp.py) — reusing that
        # signal instead of hardcoding False means uploads of the Wk1-8
        # synthetic sample set (and scripts/generate_synthetic_sample.py)
        # actually get counted in reports.py's seeded_error_catch_rate,
        # which otherwise always falls back to a placeholder since nothing
        # could ever set this to True before.
        is_synthetic=dpdp_status == DpdpStatus.compliant,
        uploaded_by=current_user.email,
        mime_type=file.content_type,
        file_size_bytes=len(raw_bytes),
    )

    document.dpdp_status = dpdp_status
    document.dpdp_reason = dpdp_reason

    db.add(document)
    db.flush()  # assigns document.id without committing yet

    storage_path = storage.save_upload(document.id, file, raw_bytes)
    document.storage_path = storage_path

    try:
        ocr_settings_row = db.get(OcrSettings, 1)
        fallback_threshold = (
            ocr_settings_row.ocr_fallback_threshold
            if ocr_settings_row is not None
            else pipeline.DEFAULT_OCR_FALLBACK_THRESHOLD
        )
        result = pipeline.process_document(raw_bytes, file.filename, file.content_type, fallback_threshold)
        document.script_type = result.script_type
        document.overall_confidence = result.overall_confidence
        document.status = DocumentStatus.extracted
        document.extraction_notes = "\n".join(result.engine_notes)

        for field_name, reading in result.fields.items():
            db.add(
                ExtractedField(
                    document_id=document.id,
                    field_name=field_name,
                    field_value=reading.value,
                    field_value_en=reading.value_en,
                    confidence=reading.confidence,
                    source=reading.source,
                )
            )
        db.flush()  # ExtractedField rows must be visible before validation.run_validations queries them
        validation.run_validations(db, document)
        diagnostics = UploadDiagnostics(primary_engine=result.primary_engine, notes=result.engine_notes)

    except Exception as exc:
        # A demo should never 500 on a bad/unusual scan — land the document
        # in a flagged state with zero fields rather than losing the upload.
        logger.exception("OCR pipeline failed for document %s", document.id)
        document.status = DocumentStatus.flagged
        document.overall_confidence = None
        document.extraction_notes = f"OCR pipeline raised an unhandled error: {exc}"
        diagnostics = UploadDiagnostics(
            primary_engine=ExtractionSource.tesseract,
            notes=[f"OCR pipeline raised an unhandled error: {exc}"],
        )
        # Still run the rule engine — mandatory_fields_present etc. will all
        # come back "fail" against zero extracted fields, which is exactly
        # the useful signal for a reviewer opening this document manually.
        validation.run_validations(db, document)

    db.commit()
    db.refresh(document)

    fields = db.query(ExtractedField).filter(ExtractedField.document_id == document.id).all()

    return UploadResponse(
        document=_to_out(document, preview_token=_upload_preview_token(current_user)),
        fields=fields,
        diagnostics=diagnostics,
    )


def _upload_preview_token(user: User) -> str:
    """The upload response needs a bearer token embedded in previewUrl too
    (see get_current_user_flexible) — reuse the same short-lived JWT the
    client already holds isn't accessible server-side, so we mint one here
    scoped to this user, matching the one issued at login."""
    from app.security import create_access_token

    return create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})


@router.get("/queue", response_model=list[WaqfDocumentOut])
def get_queue(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WaqfDocumentOut]:
    """Documents still awaiting review, oldest first."""
    docs = (
        db.query(WaqfDocument)
        .filter(WaqfDocument.status.in_([DocumentStatus.extracted, DocumentStatus.validated]))
        .order_by(WaqfDocument.uploaded_at.asc())
        .all()
    )
    token = _upload_preview_token(current_user)
    return [_to_out(d, preview_token=token) for d in docs]


@router.get("", response_model=list[WaqfDocumentOut])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WaqfDocumentOut]:
    """Every document regardless of status, newest first. Backs the Dashboard table."""
    docs = db.query(WaqfDocument).order_by(WaqfDocument.uploaded_at.desc()).all()
    token = _upload_preview_token(current_user)
    return [_to_out(d, preview_token=token) for d in docs]


@router.get("/stats/summary", response_model=DashboardStatsOut)
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardStatsOut:
    """Backs the Dashboard's four stat cards. Declared ahead of
    /{document_id} so "stats" isn't swallowed as a document id."""
    docs = db.query(WaqfDocument).all()
    pending_review = sum(1 for d in docs if d.status in (DocumentStatus.extracted, DocumentStatus.validated))
    flagged = sum(1 for d in docs if d.status == DocumentStatus.flagged)

    today = datetime.now(timezone.utc).date()
    approved_today = (
        db.query(Review)
        .filter(Review.action.in_([ReviewAction.approve, ReviewAction.correct]))
        .all()
    )
    approved_today_count = sum(1 for r in approved_today if r.reviewed_at.date() == today)

    scored = [d.overall_confidence for d in docs if d.overall_confidence is not None]
    avg_confidence = sum(scored) / len(scored) if scored else None

    return DashboardStatsOut(
        pending_review=pending_review,
        approved_today=approved_today_count,
        flagged=flagged,
        avg_confidence=avg_confidence,
    )


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailOut:
    document = db.get(WaqfDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    fields = db.query(ExtractedField).filter(ExtractedField.document_id == document_id).all()
    validations = db.query(ValidationResult).filter(ValidationResult.document_id == document_id).all()
    rule_order = {
        "mandatory_fields_present": 0,
        "survey_number_format": 1,
        "date_plausibility": 2,
        "cross_document_consistency": 3,
    }
    validations.sort(key=lambda v: rule_order.get(v.rule_name, 99))
    token = _upload_preview_token(current_user)
    return DocumentDetailOut(document=_to_out(document, preview_token=token), fields=fields, validations=validations)


@router.post("/{document_id}/revalidate", response_model=list[ValidationResultOut])
def revalidate_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ValidationResultOut]:
    """Force-reruns the Segment 3 rule engine against a document's current
    ExtractedField rows and persists the result, replacing whatever's on
    record. Exists because run_validations() otherwise only fires at upload
    time or when a reviewer submits an edited field — a document whose
    ValidationResult rows are missing (e.g. processed under an earlier
    build, before validation.py was wired into the upload endpoint) has no
    other way to get them without a reviewer editing a field first. Lets
    Review.tsx offer a manual "Re-run validation" action for that case."""
    document = db.get(WaqfDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    results = validation.run_validations(db, document)
    db.commit()

    rule_order = {
        "mandatory_fields_present": 0,
        "survey_number_format": 1,
        "date_plausibility": 2,
        "cross_document_consistency": 3,
    }
    results.sort(key=lambda v: rule_order.get(v.rule_name, 99))
    return results


@router.post("/{document_id}/review", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def submit_review(
    document_id: str,
    payload: ReviewSubmitIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewOut:
    """Records a reviewer's approve/correct/flag decision, persists any field
    corrections as an audit trail, and moves the document out of the queue.
    Mirrors the frontend's former mock `submitReview` 1:1."""
    document = db.get(WaqfDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")

    review = Review(
        document_id=document_id,
        reviewer_id=current_user.email,
        action=payload.action,
        notes=payload.notes,
        duration_seconds=payload.duration_seconds,
    )
    db.add(review)
    db.flush()  # assigns review.id for the FieldCorrection rows below

    if payload.corrections:
        fields_by_name = {
            f.field_name: f
            for f in db.query(ExtractedField).filter(ExtractedField.document_id == document_id).all()
        }
        for field_name, corrected_value in payload.corrections.items():
            field = fields_by_name.get(field_name)
            if field is None:
                continue
            db.add(
                FieldCorrection(
                    extracted_field_id=field.id,
                    review_id=review.id,
                    previous_value=field.field_value,
                    corrected_value=corrected_value,
                )
            )
            field.field_value = corrected_value
            field.confidence = 1.0
            field.source = ExtractionSource.reconciled

        db.flush()  # corrected field_value rows must be visible before re-validating
        validation.run_validations(db, document)

    document.status = DocumentStatus.flagged if payload.action == "flag" else DocumentStatus.reviewed

    db.commit()
    db.refresh(review)
    return ReviewOut.model_validate(review)


@router.get("/{document_id}/reviews", response_model=list[ReviewOut])
def get_document_reviews(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewOut]:
    """Full review history for a document, oldest first. The Dashboard uses
    this to show why a flagged document was flagged (latest action='flag')."""
    reviews = (
        db.query(Review).filter(Review.document_id == document_id).order_by(Review.reviewed_at.asc()).all()
    )
    return reviews


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str,
    current_user: User = Depends(get_current_user_flexible),
    db: Session = Depends(get_db),
):
    document = db.get(WaqfDocument, document_id)
    if document is None or not document.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found.")

    try:
        return storage.load_file_response(document.storage_path, document.mime_type, document.filename)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file is missing on disk.")
