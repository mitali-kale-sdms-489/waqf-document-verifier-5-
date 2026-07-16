"""
Idempotent startup seeding. Mirrors src/data/mockAuth.ts and the static parts
of src/data/mockAdmin.ts so the backend behaves like the frontend's mocks did
before real endpoints existed — same demo logins, same default validation
rules/OCR settings/CER benchmark. Safe to call on every startup.
"""
from sqlalchemy.orm import Session

from app.models import (
    CerBenchmarkEntry,
    OcrSettings,
    Role,
    ScriptType,
    User,
    ValidationRuleConfig,
    ValidationRuleResult,
)
from app.security import hash_password

DEMO_USERS = [
    {
        "email": "supervisor@waqf.gov.in",
        "full_name": "System Administrator",
        "password": "Supervisor@Waqf2025",
        "role": Role.SUPERVISOR,
    },
    {
        "email": "user@waqf.gov.in",
        "full_name": "Mohammed Ali",
        "password": "User@Waqf2025",
        "role": Role.USER,
    },
    {
        "email": "fatima.sheikh@waqf.gov.in",
        "full_name": "Fatima Sheikh",
        "password": "User@Waqf2025",
        "role": Role.USER,
    },
    {
        "email": "ravi.deshmukh@waqf.gov.in",
        "full_name": "Ravi Deshmukh",
        "password": "Supervisor@Waqf2025",
        "role": Role.SUPERVISOR,
    },
]

VALIDATION_RULE_DEFAULTS = [
    {
        "key": "mandatory_fields_present",
        "name": "Mandatory fields present",
        "description": "Property ID, mutawalli name, and survey number must all be extracted.",
        "severity": ValidationRuleResult.fail,
        "enabled": True,
    },
    {
        "key": "survey_number_format",
        "name": "Survey number format",
        "description": "Survey number must match the district's expected pattern (e.g. 412/2-A).",
        "severity": ValidationRuleResult.warning,
        "enabled": True,
    },
    {
        "key": "date_plausibility",
        "name": "Registration date plausibility",
        "description": "Flags registration dates outside the digitised register's valid range.",
        "severity": ValidationRuleResult.warning,
        "enabled": True,
    },
    {
        "key": "cross_document_consistency",
        "name": "Cross-document consistency",
        "description": "Cross-checks the extracted property ID against every other processed record and flags duplicates.",
        "severity": ValidationRuleResult.fail,
        "enabled": True,
    },
]

CER_BENCHMARK_DEFAULTS = [
    {"script_type": ScriptType.urdu_nastaliq, "engine": "sarvam_vision", "cer": 0.048, "sample_size": 100},
    {"script_type": ScriptType.urdu_nastaliq, "engine": "gemini_vision", "cer": 0.063, "sample_size": 100},
    {"script_type": ScriptType.urdu_nastaliq, "engine": "surya", "cer": 0.096, "sample_size": 100},
    {"script_type": ScriptType.urdu_nastaliq, "engine": "tesseract", "cer": 0.152, "sample_size": 100},
    {"script_type": ScriptType.marathi_devanagari, "engine": "sarvam_vision", "cer": 0.021, "sample_size": 100},
    {"script_type": ScriptType.marathi_devanagari, "engine": "gemini_vision", "cer": 0.028, "sample_size": 100},
    {"script_type": ScriptType.marathi_devanagari, "engine": "surya", "cer": 0.032, "sample_size": 100},
    {"script_type": ScriptType.marathi_devanagari, "engine": "tesseract", "cer": 0.039, "sample_size": 100},
]


def seed_demo_users(db: Session) -> None:
    for u in DEMO_USERS:
        if db.query(User).filter(User.email == u["email"]).first():
            continue
        db.add(
            User(
                email=u["email"],
                full_name=u["full_name"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
                active=True,
            )
        )
    db.commit()


def seed_validation_rules(db: Session) -> None:
    for r in VALIDATION_RULE_DEFAULTS:
        if db.get(ValidationRuleConfig, r["key"]):
            continue
        db.add(ValidationRuleConfig(**r))
    db.commit()


def seed_ocr_settings(db: Session) -> None:
    if db.get(OcrSettings, 1):
        return
    db.add(OcrSettings(id=1))
    db.commit()


def seed_cer_benchmark(db: Session) -> None:
    """Reconciles against CER_BENCHMARK_DEFAULTS by (script_type, engine)
    key, rather than the previous "if the table has any row at all, skip
    everything" guard. That blanket skip meant that when GPT-4o mini was
    swapped for Gemini Vision as the fallback engine, CER_BENCHMARK_DEFAULTS
    below was updated to say "gemini_vision", but the already-seeded
    "gpt4o_mini" rows from before that swap were never touched again — they
    just sat in the table forever, showing up in the admin CER benchmark
    table with a blank engine name (the frontend's engine-label lookup has
    no entry for a retired engine key) next to an otherwise-normal CER%
    and sample size.

    This runs on every startup (see main.py) and: inserts any
    (script_type, engine) pair from CER_BENCHMARK_DEFAULTS that's missing,
    updates cer/sample_size for a pair that already exists with different
    values, and deletes any row whose (script_type, engine) pair is no
    longer in CER_BENCHMARK_DEFAULTS at all — exactly what should have
    happened to the gpt4o_mini rows when that engine was retired."""
    existing = {(e.script_type, e.engine): e for e in db.query(CerBenchmarkEntry).all()}
    wanted_keys = set()
    for d in CER_BENCHMARK_DEFAULTS:
        key = (d["script_type"], d["engine"])
        wanted_keys.add(key)
        row = existing.get(key)
        if row is None:
            db.add(CerBenchmarkEntry(**d))
        elif row.cer != d["cer"] or row.sample_size != d["sample_size"]:
            row.cer = d["cer"]
            row.sample_size = d["sample_size"]
    for key, row in existing.items():
        if key not in wanted_keys:
            db.delete(row)
    db.commit()


def seed_all(db: Session) -> None:
    seed_demo_users(db)
    seed_validation_rules(db)
    seed_ocr_settings(db)
    seed_cer_benchmark(db)
