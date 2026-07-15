from collections.abc import Callable

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_user_from_token(token: str, db: Session) -> User:
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or deactivated")

    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return _resolve_user_from_token(credentials.credentials, db)


def get_current_user_flexible(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Same as get_current_user, but also accepts `?token=` — needed for the
    document-file preview endpoint, which is loaded via <img>/<iframe> `src`
    and so can't carry an Authorization header. previewUrl on WaqfDocument
    is built with this query param already attached (see routers/documents.py)."""
    if credentials is not None:
        return _resolve_user_from_token(credentials.credentials, db)
    if token:
        return _resolve_user_from_token(token, db)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def require_role(*allowed_roles: Role) -> Callable:
    """Usage: Depends(require_role(Role.SUPERVISOR))"""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this resource")
        return user

    return _check
