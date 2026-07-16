from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import DocumentStatus, ValidationResult, WaqfDocument
from app.routers import admin, auth, documents, reports
import app.models
from app.seed import seed_all
from app.services import validation

settings = get_settings()

app = FastAPI(
    title="Waqf Document Verifier API",
    description="POC-C — DocVerify Chain Extension backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _migrate_ocr_settings_columns() -> None:
    """Base.metadata.create_all only creates tables that don't exist yet —
    it won't add a column to an ocr_settings table created before
    ocr_fallback_threshold existed. This is a lightweight patch so existing
    dev databases (SQLite or Postgres — plain ADD COLUMN works on both)
    don't 500 on startup; a real migration tool (Alembic) would replace
    this once there's more than one such column."""
    inspector = inspect(engine)
    if "ocr_settings" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("ocr_settings")}
    if "ocr_fallback_threshold" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE ocr_settings ADD COLUMN ocr_fallback_threshold FLOAT DEFAULT 0.6"))


def _migrate_extracted_fields_columns() -> None:
    """Same rationale as _migrate_ocr_settings_columns above — adds
    field_value_en to any extracted_fields table that pre-dates the
    English-translation feature."""
    inspector = inspect(engine)
    if "extracted_fields" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("extracted_fields")}
    if "field_value_en" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE extracted_fields ADD COLUMN field_value_en TEXT"))


def _migrate_enum_values(table: str, column: str, required_values: set[str]) -> None:
    """Postgres backs `Enum(...)` columns with a real native ENUM type when
    the table is freshly created via `Base.metadata.create_all`, and that
    call won't add new values to an enum type that already exists (same
    limitation as the column-add case above). This adds any of
    `required_values` missing from the live enum type for `table.column`,
    run outside a transaction block — Postgres doesn't allow using a value
    added this way in the same transaction it was added in, so this uses
    its own autocommit connection rather than `engine.begin()`.

    No-op on SQLite (plain text column, no enum constraint to update), and
    also no-op on Postgres if the column isn't actually backed by a native
    enum type. That second case is real, not theoretical: on a deployment
    where this table/column predates it being declared `Enum(...)` in
    models.py, `information_schema.columns.udt_name` comes back as the
    column's real underlying type — e.g. literally 'text' for a plain text
    column — and running `ALTER TYPE text ADD VALUE ...` against that
    fails with `psycopg2.errors.WrongObjectType: text is not an enum`
    (this crashed startup entirely before this check was added). Checking
    `pg_type.typtype = 'e'` first tells a genuine custom enum apart from a
    builtin type name that happens to come back from the same column, and
    in the plain-text case there's nothing to migrate anyway — new values
    just work as ordinary strings."""
    if not settings.database_url.startswith("postgres"):
        return
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        # Look up the real enum type name rather than assuming SQLAlchemy's
        # default naming — avoids silently no-op'ing (or erroring) if it
        # was created with an explicit `name=` at some point.
        type_name = conn.execute(text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ), {"table": table, "column": column}).scalar()
        if not type_name:
            return
        is_native_enum = conn.execute(text(
            "SELECT 1 FROM pg_type WHERE typname = :type_name AND typtype = 'e'"
        ), {"type_name": type_name}).scalar()
        if not is_native_enum:
            return
        existing_labels = set(conn.execute(text(
            "SELECT e.enumlabel FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = :type_name"
        ), {"type_name": type_name}).scalars().all())
        for value in sorted(required_values - existing_labels):
            # ALTER TYPE ... ADD VALUE doesn't support bind parameters for
            # the value itself; these are fixed, code-controlled enum
            # members (not user input), so interpolating is safe here.
            conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"))


def _backfill_validations() -> None:
    """Segment 3 lands validation.run_validations() partway through this
    project's life — any WaqfDocument uploaded before this existed (e.g. the
    handful of demo PDFs already sitting in storage/uploads from earlier
    testing) has extracted fields but zero ValidationResult rows. Rather
    than requiring a re-upload to see validations, run the engine once at
    startup for any extracted/validated document that doesn't have any yet.
    Cheap no-op on a fresh DB, and safe to leave in permanently (it only
    ever touches documents with zero existing ValidationResult rows)."""
    db = SessionLocal()
    try:
        candidates = (
            db.query(WaqfDocument)
            .filter(WaqfDocument.status.in_([DocumentStatus.extracted, DocumentStatus.validated]))
            .all()
        )
        for document in candidates:
            has_validations = (
                db.query(ValidationResult).filter(ValidationResult.document_id == document.id).first()
                is not None
            )
            if has_validations:
                continue
            validation.run_validations(db, document)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    # Segment 1: just users + admin-config tables are seeded. Segments 2-4
    # add the routers that read/write the rest of this schema.
    Base.metadata.create_all(bind=engine)
    _migrate_ocr_settings_columns()
    _migrate_extracted_fields_columns()
    _migrate_enum_values("extracted_fields", "source", {"gemini_vision"})
    _migrate_enum_values("ocr_settings", "primary_engine", {"gemini_vision"})
    _migrate_enum_values("waqf_documents", "script_type", {"hindi_devanagari", "sanskrit_devanagari"})
    _migrate_enum_values("cer_benchmark_entries", "script_type", {"hindi_devanagari", "sanskrit_devanagari"})
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    _backfill_validations()


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "sarvam_configured": settings.sarvam_configured,
        "gemini_configured": settings.gemini_configured,
        "shasan_configured": settings.shasan_configured,
        "s3_configured": settings.s3_configured,
    }


app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(documents.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(reports.router, prefix=settings.api_v1_prefix)
