"""
Schemas for Segment 4 admin endpoints. Shapes mirror the frontend's former
mocks in src/data/mockAdmin.ts (AdminUser, ValidationRuleConfig,
CerBenchmarkEntry/CerBenchmarkResult) 1:1, using camelCase output the same
way schemas_documents.py does.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from app.models import Role, ScriptType, ValidationRuleResult


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class AdminUserOut(CamelModel):
    id: int
    full_name: str
    email: str
    role: Role
    active: bool
    last_login_at: datetime | None


class CreateUserIn(CamelModel):
    full_name: str = Field(min_length=2)
    email: EmailStr
    role: Role


class CreateUserOut(AdminUserOut):
    """Same shape as AdminUserOut plus a one-time temporary password — the
    frontend's mock createUser() never collected a password (admin-created
    accounts have nowhere else to get one from), so the backend generates
    one and returns it here once. Extra field beyond AdminUserOut, same
    pattern as UploadDiagnostics on the upload response: additive, doesn't
    change the shape the frontend already expects if it ignores the field."""

    temporary_password: str


class UpdateUserRoleIn(CamelModel):
    role: Role


class SetUserActiveIn(CamelModel):
    active: bool


# ---------------------------------------------------------------------------
# Validation-rule config
# ---------------------------------------------------------------------------
class ValidationRuleConfigOut(CamelModel):
    key: str
    name: str
    description: str
    severity: ValidationRuleResult
    enabled: bool


class ValidationRuleConfigUpdateIn(CamelModel):
    enabled: bool


# ---------------------------------------------------------------------------
# CER benchmark (Week 9 deliverable)
# ---------------------------------------------------------------------------
class CerBenchmarkEntryOut(CamelModel):
    script_type: ScriptType
    engine: str  # includes "surya", not in ExtractionSource
    cer: float
    sample_size: int


class CerBenchmarkResponse(CamelModel):
    entries: list[CerBenchmarkEntryOut]
    # Lowest-CER engine per script — the "engine selected per script" call
    # from the Week 9 demo-gate. Keyed by ScriptType.value so it serializes
    # as a plain string-keyed object.
    selected_engine: dict[str, str]
