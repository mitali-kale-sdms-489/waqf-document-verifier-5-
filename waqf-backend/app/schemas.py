"""
Pydantic schemas for Segment 1 (auth). Field names are chosen to match the
frontend's src/types/auth.ts AuthUser shape exactly (it already uses
snake_case for full_name, so no alias juggling is needed there). Request
bodies mirror src/schemas/auth.ts (loginSchema/registerSchema), which *do*
use camelCase (fullName) — handled here with populate_by_name + alias.
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class UserOut(BaseModel):
    """Matches AuthUser in src/types/auth.ts exactly."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: Role
    full_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool | None = Field(default=None, alias="rememberMe")

    model_config = ConfigDict(populate_by_name=True)


class RegisterRequest(BaseModel):
    full_name: str = Field(alias="fullName", min_length=2)
    email: EmailStr
    password: str = Field(min_length=8)

    model_config = ConfigDict(populate_by_name=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
