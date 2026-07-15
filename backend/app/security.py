from datetime import datetime, timedelta, timezone
import secrets
import string

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()

# NOTE: we call `bcrypt` directly instead of going through passlib's
# CryptContext. passlib==1.7.4 (unmaintained since 2020) probes
# `bcrypt.__about__.__version__` to detect the installed bcrypt version,
# an attribute that bcrypt>=4.1 removed. That probe throws before passlib
# ever checks the actual password, so every login fails with a misleading
# "password cannot be longer than 72 bytes" error. Calling bcrypt ourselves
# sidesteps that broken detection code entirely.

_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pw_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # malformed/foreign hash format
        return False


def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode: dict = {"sub": subject, "exp": expire}
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_temporary_password(length: int = 12) -> str:
    """Used when an admin creates a user via POST /admin/users — the
    frontend's create-user form never collects a password (see
    Admin.tsx / mockAdmin.ts createUser), so the backend has to mint one
    for the account to actually be usable. Returned once in the response
    (schemas_admin.CreateUserOut.temporary_password); only its bcrypt hash
    is ever persisted."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))
