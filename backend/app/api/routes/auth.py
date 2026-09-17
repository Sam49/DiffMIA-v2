from __future__ import annotations

import logging
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ValidationError,
)
from app.core.mailer import (
    confirm_email_verification,
    request_password_reset,
    request_verification_by_email,
    request_verification_email,
    reset_password as apply_password_reset,
)
from app.core.google_oauth import (
    LINK_INTENT,
    attach_google_identity,
    build_authorize_url,
    consume_state,
    detach_google_identity,
    exchange_code,
    get_or_create_google_user,
    google_configured,
    make_state,
)
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleLinkStartOut,
    LoginRequest,
    OAuthStatus,
    PasswordChange,
    RegisterRequest,
    RegistrationStatus,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
    VerificationInfo,
    VerifyEmailRequest,
)

logger = logging.getLogger("diffmia.auth")

router = APIRouter(tags=["auth"])
_limiter = SlidingWindowLimiter(max_requests=max(get_settings().login_rate_limit_per_minute, 1))


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, email=user.email,
                   role=UserRole(user.role), is_active=user.is_active,
                   auth_provider=user.auth_provider, email_verified=user.email_verified,
                   google_linked=user.google_linked,
                   created_at=user.created_at)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"login:{client}"):
        raise AuthenticationError("Too many login attempts. Try again later.")
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid username or password.")
    if not user.is_active:
        raise AuthenticationError("Account is disabled.")
    settings = get_settings()
    if not user.email_verified:
        raise AuthenticationError(
            "Please verify your email address before signing in.",
            code="EMAIL_NOT_VERIFIED",
        )
    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role},
        settings.secret_key,
        settings.access_token_expire_minutes,
    )
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post("/auth/change-password", response_model=UserOut)
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    if not verify_password(payload.old_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    return _user_out(user)


# ── Admin user management ────────────────────────────────────────
@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> UserOut:
    existing = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"User '{payload.username}' already exists.")
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role.value if isinstance(payload.role, UserRole) else str(payload.role),
    )
    db.add(user)
    db.flush()
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    actor: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> UserOut:
    if actor.id == user_id and payload.is_active is False:
        raise ValidationError("An admin cannot deactivate its own account.")
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} does not exist.")
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role.value if isinstance(payload.role, UserRole) else str(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.add(user)
    return _user_out(user)


# ── Google OAuth single sign-on ──────────────────────────────────
def _mint_token(user: User) -> str:
    settings = get_settings()
    return create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role},
        settings.secret_key,
        settings.access_token_expire_minutes,
    )


def _mint_handoff_token(user: User) -> str:
    """Short-lived token carried in the redirect fragment, exchanged once."""
    return create_access_token(
        {
            "sub": str(user.id),
            "username": user.username,
            "role": user.role,
            "typ": "oauth_handoff",
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
        },
        get_settings().secret_key,
        2,
    )


@router.get("/auth/oauth/status", response_model=OAuthStatus)
def oauth_status() -> OAuthStatus:
    settings = get_settings()
    return OAuthStatus(
        google_enabled=google_configured(),
        self_registration=settings.registration_enabled,
        email_verification_required=settings.email_verification_required,
    )


# ── Self-service registration ────────────────────────────────────
@router.get("/auth/registration/status", response_model=RegistrationStatus)
def registration_status() -> RegistrationStatus:
    return RegistrationStatus(registration_enabled=get_settings().registration_enabled)


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Open sign-up. Disabled unless REGISTRATION_ENABLED=true."""
    settings = get_settings()
    if not settings.registration_enabled:
        raise PermissionDeniedError("Registration is disabled on this server.")
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"register:{client}"):
        raise ValidationError("Too many registration attempts. Try again later.")
    username = payload.username.strip()
    email = payload.email.strip().lower()
    existing = db.execute(
        select(User).where((User.username == username) | (User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.username == username:
            raise ConflictError(f"Username '{username}' is already taken.")
        raise ConflictError("An account with this email already exists.")
    role = settings.registration_default_role.upper()
    if role not in {r.value for r in UserRole} or role == UserRole.ADMIN.value:
        role = UserRole.VIEWER.value
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(payload.password),
        role=role,
        auth_provider="local",
        email_verified=not settings.email_verification_required,
    )
    db.add(user)
    db.flush()

    verification: VerificationInfo | None = None
    if settings.email_verification_required:
        outcome = request_verification_email(db, user)
        development_token = (
            outcome.get("development_token")
            if settings.app_env != "production"
            else None
        )
        verification = VerificationInfo(required=True, development_token=development_token)
    return TokenResponse(access_token=_mint_token(user), user=_user_out(user), verification=verification)


# ── Email verification & password reset ──────────────────────────
@router.post("/auth/verify-email", response_model=UserOut)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> UserOut:
    user = confirm_email_verification(db, payload.token)
    return _user_out(user)


@router.post("/auth/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Always responds uniformly — never discloses whether the account exists."""
    return request_password_reset(db, payload.email, request)


@router.post("/auth/resend-verification-email")
def resend_verification_email(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Public resend keyed by email — for accounts that cannot sign in yet.
    Uniform response; only unverified, active, local accounts get mail."""
    return request_verification_by_email(db, payload.email, request)


@router.post("/auth/reset-password", response_model=UserOut)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> UserOut:
    user = apply_password_reset(db, payload.token, payload.new_password)
    return _user_out(user)


def _require_google_configured() -> None:
    if not google_configured():
        raise ValidationError(
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
            code="OAUTH_NOT_CONFIGURED",
        )


def _callback_redirect_uri(request: Request) -> str:
    settings = get_settings()
    return settings.oauth_redirect_uri or str(request.base_url).rstrip("/") + "/api/auth/google/callback"


@router.get("/auth/google/authorize")
def google_authorize(request: Request) -> RedirectResponse:
    _require_google_configured()
    state = make_state(request.client.host if request.client else "unknown")
    return RedirectResponse(
        build_authorize_url(_callback_redirect_uri(request), state), status_code=302
    )


#: Where a link flow lands when it cannot be completed.
def _complete_link(
    payload: dict, claims: dict, db: Session, frontend: str
) -> RedirectResponse:
    """Finish a Settings-initiated link: attach Google to the signed-in account."""

    def _fail(code: str, message: str) -> RedirectResponse:
        return RedirectResponse(
            f"{frontend}/settings?google_error={code}&message={quote(message, safe='')}",
            status_code=302,
        )

    user = db.get(User, int(payload.get("uid") or 0))
    if user is None or not user.is_active:
        return _fail("OAUTH_FAILED", "The account is no longer available.")
    try:
        attach_google_identity(claims, user, db)
        db.commit()
    except ConflictError:
        db.rollback()
        return _fail(
            "GOOGLE_ALREADY_LINKED",
            "That Google account is already linked to another DiffMIA account.",
        )
    except Exception:  # noqa: BLE001 - a browser redirect must never 500
        logger.warning("Google link failed", exc_info=True)
        db.rollback()
        return _fail("OAUTH_FAILED", "Google could not be linked. Please try again.")
    return RedirectResponse(f"{frontend}/settings#google=linked", status_code=302)


@router.post("/auth/google/link/start", response_model=GoogleLinkStartOut)
def google_link_start(
    request: Request,
    user: User = Depends(get_current_user),
) -> GoogleLinkStartOut:
    """Begin linking Google to the signed-in account.

    The account is bound into the signed ``state`` (never the query string), and
    the browser is sent to the returned URL — a plain redirect cannot carry the
    Authorization header, so the flow must not depend on the session cookie.
    """
    _require_google_configured()
    state = make_state(
        request.client.host if request.client else "unknown",
        intent=LINK_INTENT,
        user_id=user.id,
    )
    return GoogleLinkStartOut(authorize_url=build_authorize_url(_callback_redirect_uri(request), state))


@router.post("/auth/google/unlink", response_model=UserOut)
def google_unlink(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """Detach the Google identity; the password remains as the way in."""
    detach_google_identity(user, db)
    db.commit()
    db.refresh(user)
    return _user_out(user)


#: Google error codes safe to echo back to a browser.
_KNOWN_GOOGLE_CALLBACK_ERRORS = frozenset(
    {
        "invalid_request",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
        "unauthorized_client",
    }
)


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    settings = get_settings()
    frontend = settings.oauth_frontend_origin.rstrip("/")

    def _fail(error_code: str, message: str) -> RedirectResponse:
        return RedirectResponse(
            f"{frontend}/login?oauth_error={error_code}&message={quote(message, safe='')}",
            status_code=302,
        )

    if error:
        # Google reports refusals and client errors here. `error` is
        # attacker-controllable query text, so it is allowlisted before being
        # reflected anywhere in the response.
        if error == "access_denied":
            return _fail("OAUTH_CANCELLED", "You cancelled the Google sign-in.")
        if error in _KNOWN_GOOGLE_CALLBACK_ERRORS:
            return _fail("OAUTH_GOOGLE_ERROR", f"Google refused the sign-in ({error}).")
        return _fail("OAUTH_CANCELLED", "Google sign-in was cancelled or was denied.")
    if not code or not state:
        return _fail("OAUTH_INVALID_RESPONSE", "Google did not return the expected parameters.")

    client_ip = request.client.host if request.client else "unknown"
    try:
        payload = consume_state(state, client_ip)
    except Exception as exc:  # noqa: BLE001 - a browser redirect must never 500
        logger.warning("Google OAuth state rejected (%s): %s", type(exc).__name__, exc)
        return _fail(
            "OAUTH_STATE_INVALID",
            "This sign-in attempt expired, was already used, or was started in "
            "another browser session. Please start again.",
        )

    # The same helper the authorize step uses, so the URI Google validates and
    # the URI we exchange with can never diverge.
    redirect_uri = _callback_redirect_uri(request)
    try:
        claims = exchange_code(code, redirect_uri)
    except ProviderError as exc:
        # Curated, non-secret explanation of Google's own error code: this is
        # what makes an operator-facing diagnosis possible from the UI alone.
        logger.warning("Google token exchange failed: %s", exc)
        return _fail("OAUTH_TOKEN_EXCHANGE", str(exc))
    except Exception as exc:  # noqa: BLE001 - a browser redirect must never 500
        logger.warning("Google token exchange failed (%s): %s", type(exc).__name__, exc)
        return _fail("OAUTH_FAILED", "Google sign-in could not be completed. Please try again.")

    if payload.get("intent") == LINK_INTENT:
        return _complete_link(payload, claims, db, frontend)

    try:
        user = get_or_create_google_user(claims, db)
    except PermissionDeniedError as exc:
        logger.warning("Google sign-in refused: %s", exc)
        return _fail("OAUTH_ACCOUNT_DISABLED", str(exc))
    except Exception:  # noqa: BLE001 - a browser redirect must never 500
        logger.warning("Google sign-in provisioning failed", exc_info=True)
        return _fail("OAUTH_FAILED", "Google sign-in could not be completed. Please try again.")

    token = _mint_handoff_token(user)
    # Token travels in the URL fragment: browsers never send fragments to
    # servers, so it cannot leak via Referer headers or access logs.
    return RedirectResponse(f"{frontend}/oauth/callback#token={token}", status_code=302)


@router.post("/auth/oauth/exchange", response_model=TokenResponse)
def oauth_exchange(request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """One-time handoff: swap the fragment token for a normal login response."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()
    payload = decode_access_token(token, settings.secret_key)
    if payload.get("typ") != "oauth_handoff":
        raise AuthenticationError("Invalid handoff token.")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise AuthenticationError("Account is disabled or no longer exists.")
    return TokenResponse(access_token=_mint_token(user), user=_user_out(user))
