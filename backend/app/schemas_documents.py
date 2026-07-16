"""
Schemas for Segment 2 (documents/upload/OCR). Field names mirror
src/types/domain.ts on the frontend exactly (WaqfDocument, ExtractedField),
using camelCase output — FastAPI's default `response_model_by_alias=True`
means CamelModel subclasses serialize with the alias (camelCase) automatically.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models import (
    DocumentStatus,
    DpdpStatus,
    ExtractionSource,
    FieldName,
    ReviewAction,
    ScriptType,
    ValidationRuleResult,
)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ExtractedFieldOut(CamelModel):
    id: str
    document_id: str
    field_name: FieldName
    field_value: str | None
    # English transliteration/rendering, populated by the Gemini translation
    # pass (see app/services/ocr/gemini_engine.run_gemini_translation).
    # None for English/Latin-script docs, pre-existing records, or a failed/
    # unconfigured translation call.
    field_value_en: str | None = None
    confidence: float
    source: ExtractionSource


class ValidationResultOut(CamelModel):
    id: str
    document_id: str
    rule_name: str
    result: ValidationRuleResult
    message: str


class WaqfDocumentOut(CamelModel):
    id: str
    filename: str
    status: DocumentStatus
    script_type: ScriptType
    is_synthetic: bool
    dpdp_status: DpdpStatus
    dpdp_reason: str | None
    uploaded_at: datetime
    uploaded_by: str
    overall_confidence: float | None
    preview_url: str | None = None
    mime_type: str | None
    file_size_bytes: int | None
    # Newline-joined OCR pipeline diagnostics (which engine won, any
    # script-hint corrections, why the translation pass did/didn't
    # populate field_value_en) — see WaqfDocument.extraction_notes in
    # app/models.py. Optional/None for pre-existing records saved before
    # this was tracked.
    extraction_notes: str | None = None


class DocumentDetailOut(CamelModel):
    document: WaqfDocumentOut
    fields: list[ExtractedFieldOut]
    # Populated by Segment 3's validation-rule engine (app/services/validation.py).
    validations: list[ValidationResultOut]


class UploadDiagnostics(CamelModel):
    """Not in the frontend's WaqfDocument type — surfaced separately so the
    upload response stays useful for debugging which OCR engine actually
    ran, without changing the shape the frontend already expects."""

    primary_engine: ExtractionSource
    notes: list[str]


class UploadResponse(CamelModel):
    document: WaqfDocumentOut
    fields: list[ExtractedFieldOut]
    diagnostics: UploadDiagnostics


class DashboardStatsOut(CamelModel):
    pending_review: int
    approved_today: int
    flagged: int
    avg_confidence: float | None


class ReviewSubmitIn(CamelModel):
    """POST /documents/{id}/review body. Mirrors the args to the frontend's
    former mock `submitReview(documentId, action, opts)`."""

    action: ReviewAction
    notes: str | None = None
    # Keyed by FieldName — only fields the reviewer actually edited need to
    # be present. Matches Review.tsx's `edits` record shape 1:1.
    corrections: dict[FieldName, str] | None = None
    duration_seconds: int | None = None


class ReviewOut(CamelModel):
    id: str
    document_id: str
    reviewer_id: str
    action: ReviewAction
    notes: str | None
    reviewed_at: datetime
    duration_seconds: int | None


class OcrSettingsOut(CamelModel):
    """primary_engine is read-only (always sarvam_vision) — engine choice is
    automatic now, see app/services/ocr/pipeline.py."""

    primary_engine: ExtractionSource
    use_reconciliation: bool
    auto_approve_high_confidence: bool
    high_confidence_threshold: float
    low_confidence_threshold: float
    ocr_fallback_threshold: float


class OcrSettingsUpdate(CamelModel):
    """Every field optional so PATCH can update just one setting at a time.
    primary_engine is deliberately absent — it's no longer a supervisor-set
    value, so there's nothing to accept here even if a client sends it."""

    use_reconciliation: bool | None = None
    auto_approve_high_confidence: bool | None = None
    high_confidence_threshold: float | None = None
    low_confidence_threshold: float | None = None
    ocr_fallback_threshold: float | None = None
