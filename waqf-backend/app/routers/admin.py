"""
Admin-config endpoints. Segment 4 in the project doc.

GET/PATCH /admin/ocr-settings replaces what used to be a frontend-only mock
(src/data/mockAdmin.ts) that a supervisor could "edit" in the Admin page
without it having any effect on real document processing — the OcrSettings
DB row existed from Segment 1 onward but nothing ever read or wrote it.
primary_engine is intentionally read-only here: Sarvam Vision 3B is always
tried first by the pipeline, which now compares its confidence against
Tesseract and Gemini Vision automatically instead of running whichever
engine this field named (see app/services/ocr/pipeline.py).

Segment 4 additions below: user management, validation-rule config
(enable/disable the rules Segment 3's engine runs), and the Week-9 CER
benchmark report.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.deps import require_role
from app.models import (
    CerBenchmarkEntry,
    OcrSettings,
    Role,
    ScriptType,
    User,
    ValidationRuleConfig,
)
from app.schemas_admin import (
    AdminUserOut,
    CerBenchmarkEntryOut,
    CerBenchmarkResponse,
    CreateUserIn,
    CreateUserOut,
    SetUserActiveIn,
    UpdateUserRoleIn,
    ValidationRuleConfigOut,
    ValidationRuleConfigUpdateIn,
)
from app.schemas_documents import OcrSettingsOut, OcrSettingsUpdate
from app.security import generate_temporary_password, hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_or_create(db: Session) -> OcrSettings:
    row = db.get(OcrSettings, 1)
    if row is None:
        row = OcrSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/ocr-settings", response_model=OcrSettingsOut)
def get_ocr_settings(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> OcrSettingsOut:
    return OcrSettingsOut.model_validate(_get_or_create(db))


@router.patch("/ocr-settings", response_model=OcrSettingsOut)
def update_ocr_settings(
    payload: OcrSettingsUpdate,
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> OcrSettingsOut:
    row = _get_or_create(db)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return OcrSettingsOut.model_validate(row)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    users = db.query(User).order_by(User.full_name.asc()).all()
    return [AdminUserOut.model_validate(u) for u in users]


@router.post("/users", response_model=CreateUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserIn,
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> CreateUserOut:
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists.")

    temporary_password = generate_temporary_password()
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(temporary_password),
        role=payload.role,
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return CreateUserOut(
        **AdminUserOut.model_validate(user).model_dump(),
        temporary_password=temporary_password,
    )


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
def update_user_role(
    user_id: int,
    payload: UpdateUserRoleIn,
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = _get_user_or_404(db, user_id)
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}/active", response_model=AdminUserOut)
def set_user_active(
    user_id: int,
    payload: SetUserActiveIn,
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = _get_user_or_404(db, user_id)
    if user.id == current_user.id and not payload.active:
        # A supervisor deactivating their own only active account would
        # lock everyone out of user management with no way back in short
        # of a DB edit — the frontend's mock never had to consider this
        # since it never persisted anything real.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't deactivate your own account.")
    user.active = payload.active
    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(user)


# ---------------------------------------------------------------------------
# Validation-rule config (gates app/services/validation.py's rule set)
# ---------------------------------------------------------------------------
@router.get("/validation-rules", response_model=list[ValidationRuleConfigOut])
def list_validation_rules(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> list[ValidationRuleConfigOut]:
    rows = db.query(ValidationRuleConfig).order_by(ValidationRuleConfig.key.asc()).all()
    return [ValidationRuleConfigOut.model_validate(r) for r in rows]


@router.patch("/validation-rules/{key}", response_model=ValidationRuleConfigOut)
def update_validation_rule(
    key: str,
    payload: ValidationRuleConfigUpdateIn,
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> ValidationRuleConfigOut:
    row = db.get(ValidationRuleConfig, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown validation rule.")
    row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return ValidationRuleConfigOut.model_validate(row)


# ---------------------------------------------------------------------------
# CER benchmark (Week 9 deliverable: "CER reported per script per engine on
# the sample set; engine selected per script.")
# ---------------------------------------------------------------------------
@router.get("/cer-benchmark", response_model=CerBenchmarkResponse)
def get_cer_benchmark(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> CerBenchmarkResponse:
    rows = db.query(CerBenchmarkEntry).all()
    entries = [CerBenchmarkEntryOut.model_validate(r) for r in rows]

    selected_engine: dict[str, str] = {}
    for script in ScriptType:
        script_entries = [e for e in entries if e.script_type == script]
        if not script_entries:
            continue
        best = min(script_entries, key=lambda e: e.cer)
        selected_engine[script.value] = best.engine

    return CerBenchmarkResponse(entries=entries, selected_engine=selected_engine)
