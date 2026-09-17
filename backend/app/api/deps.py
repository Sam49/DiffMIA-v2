from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import user_var
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()
    payload = decode_access_token(token, settings.secret_key)
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise AuthenticationError("Account is disabled or no longer exists.")
    if not user.email_verified:
        raise AuthenticationError(
            "Please verify your email address before signing in.",
            code="EMAIL_NOT_VERIFIED",
        )
    user_var.set(user.username)
    return user


def require_roles(*roles: str) -> Callable:
    """Role guard. ADMIN always passes."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role == "ADMIN" or user.role in roles:
            return user
        raise PermissionDeniedError(
            f"Role '{user.role}' is not allowed to perform this action "
            f"(requires one of: {', '.join(roles)})."
        )

    return dependency
