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
    if db.query(CerBenchmarkEntry).first():
        return
    for e in CER_BENCHMARK_DEFAULTS:
        db.add(CerBenchmarkEntry(**e))
    db.commit()


def seed_all(db: Session) -> None:
    seed_demo_users(db)
    seed_validation_rules(db)
    seed_ocr_settings(db)
    seed_cer_benchmark(db)
