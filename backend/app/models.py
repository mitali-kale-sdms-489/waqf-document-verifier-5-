"""
ORM models. Field names/enums are kept 1:1 with the frontend's
src/types/domain.ts and src/types/auth.ts so serializers in later segments
are a straight field-for-field mapping (see app/schemas.py).

Only the `User` model is wired to a router in this segment (auth). Every
other table is defined now so Segment 2/3/4 don't need migrations for new
tables — just new routers/services on top of this schema.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class Role(str, enum.Enum):
    USER = "USER"
    SUPERVISOR = "SUPERVISOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False, default=Role.USER)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Documents / extraction / validation / review
# ---------------------------------------------------------------------------
class ScriptType(str, enum.Enum):
    urdu_nastaliq = "urdu_nastaliq"
    marathi_devanagari = "marathi_devanagari"
    english_latin = "english_latin"
    hindi_devanagari = "hindi_devanagari"
    sanskrit_devanagari = "sanskrit_devanagari"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    extracted = "extracted"
    validated = "validated"
    reviewed = "reviewed"
    approved = "approved"
    flagged = "flagged"


class DpdpStatus(str, enum.Enum):
    checking = "checking"
    compliant = "compliant"
    needs_review = "needs_review"


class FieldName(str, enum.Enum):
    property_id = "property_id"
    mutawalli_name = "mutawalli_name"
    survey_number = "survey_number"
    registration_date = "registration_date"
    extent = "extent"
    village = "village"


MANDATORY_FIELDS = [FieldName.property_id, FieldName.mutawalli_name, FieldName.survey_number]


class ExtractionSource(str, enum.Enum):
    sarvam_vision = "sarvam_vision"
    tesseract = "tesseract"
    shasan_slm = "shasan_slm"  # kept for old rows written before the Qwen swap; no longer produced
    gpt4o_mini = "gpt4o_mini"  # kept for old rows written before the Gemini swap; no longer produced
    gemini_vision = "gemini_vision"
    qwen_slm = "qwen_slm"  # Qwen2.5 via local Ollama — replaced shasan_slm as the mapping-stage engine
    reconciled = "reconciled"


class ValidationRuleResult(str, enum.Enum):
    pass_ = "pass"
    fail = "fail"
    warning = "warning"


class ReviewAction(str, enum.Enum):
    approve = "approve"
    correct = "correct"
    flag = "flag"


class WaqfDocument(Base):
    __tablename__ = "waqf_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("doc"))
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus),
        default=DocumentStatus.uploaded,
    )
    script_type: Mapped[ScriptType] = mapped_column(Enum(ScriptType), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    dpdp_status: Mapped[DpdpStatus] = mapped_column(
        Enum(DpdpStatus),
        default=DpdpStatus.checking,
    )
    dpdp_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
    )
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)

    overall_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Newline-joined copy of the OCR pipeline's engine_notes (see
    # services/ocr/pipeline.py's PipelineResult.engine_notes) — which
    # engine won, any script-hint corrections that were made, and why the
    # translation pass did or didn't populate value_en. Previously this
    # only existed transiently in the upload response (UploadResult.
    # diagnostics.notes) and was lost the moment you navigated away from
    # the upload screen, which made "why didn't translation show up on
    # this document" impossible to answer later from the Review screen —
    # persisting it here is what src/pages/Review.tsx's diagnostics panel
    # reads from.
    extraction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stores either a local file path (development)
    # or an S3 object key such as:
    # uploads/2026/07/document123.pdf
    storage_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    mime_type: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )

    validations: Mapped[list["ValidationResult"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("fld"))
    document_id: Mapped[str] = mapped_column(ForeignKey("waqf_documents.id"), nullable=False)
    field_name: Mapped[FieldName] = mapped_column(Enum(FieldName), nullable=False)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # English transliteration/rendering of field_value (see
    # app/services/ocr/gemini_engine.run_gemini_translation). Null for
    # English/Latin-script documents, for records extracted before this
    # column existed, or when the Gemini translation call failed/wasn't
    # configured — always optional, never required for a document to be
    # reviewed or approved.
    field_value_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[ExtractionSource] = mapped_column(Enum(ExtractionSource), nullable=False)

    document: Mapped["WaqfDocument"] = relationship(back_populates="fields")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("val"))
    document_id: Mapped[str] = mapped_column(ForeignKey("waqf_documents.id"), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[ValidationRuleResult] = mapped_column(Enum(ValidationRuleResult), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["WaqfDocument"] = relationship(back_populates="validations")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("rev"))
    document_id: Mapped[str] = mapped_column(ForeignKey("waqf_documents.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(255), nullable=False)  # email
    action: Mapped[ReviewAction] = mapped_column(Enum(ReviewAction), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped["WaqfDocument"] = relationship(back_populates="reviews")
    corrections: Mapped[list["FieldCorrection"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class FieldCorrection(Base):
    __tablename__ = "field_corrections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("cor"))
    extracted_field_id: Mapped[str] = mapped_column(ForeignKey("extracted_fields.id"), nullable=False)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    review: Mapped["Review"] = relationship(back_populates="corrections")


# ---------------------------------------------------------------------------
# Admin config (Segment 4 will add routers; schema lives here from the start)
# ---------------------------------------------------------------------------
class ValidationRuleConfig(Base):
    """Backs GET/PATCH /api/v1/admin/validation-rules."""

    __tablename__ = "validation_rule_configs"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[ValidationRuleResult] = mapped_column(Enum(ValidationRuleResult), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class OcrSettings(Base):
    """Single-row table backing GET/PATCH /api/v1/admin/ocr-settings.

    primary_engine is kept for display only — Sarvam Vision 3B is always
    tried first by the pipeline, so this is no longer a supervisor-editable
    choice (see app/services/ocr/pipeline.py for why: the pipeline now
    compares confidence across all three engines automatically instead of
    running whichever one this field named)."""

    __tablename__ = "ocr_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    primary_engine: Mapped[ExtractionSource] = mapped_column(
        Enum(ExtractionSource), default=ExtractionSource.sarvam_vision
    )
    use_reconciliation: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_approve_high_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    high_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.9)
    low_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    # Below this, Sarvam Vision's own OCR confidence is treated as too low
    # to trust on its own, so Tesseract and GPT-4o mini are also run and
    # compared against it (see pipeline.DEFAULT_OCR_FALLBACK_THRESHOLD).
    ocr_fallback_threshold: Mapped[float] = mapped_column(Float, default=0.6)


class CerBenchmarkEntry(Base):
    """Backs GET /api/v1/admin/cer-benchmark (Week 9 deliverable)."""

    __tablename__ = "cer_benchmark_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: _uuid("cer"))
    script_type: Mapped[ScriptType] = mapped_column(Enum(ScriptType), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)  # includes "surya", not in ExtractionSource
    cer: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
