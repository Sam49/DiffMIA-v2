"""Google OAuth2 single sign-on.

Implements the standard Google Web OAuth2 flow with strict CSRF protection:

1. ``GET /auth/google/authorize`` — mints a signed, single-use ``state``
   (HMAC, short TTL, bound to the client IP) and 302s to Google's consent
   screen. The state also carries an *intent*: the same callback either signs a
   user in (``login``) or attaches a Google identity to the already signed-in
   account that started the flow from Settings (``link``), which is why the
   intent and target user are bound into the signed payload rather than trusted
   from the query string.
2. Google redirects to ``GET /auth/google/callback`` with ``code`` + ``state``.
   The state is verified and one-time (a JTI tombstone is persisted so a
   replayed callback is rejected). The code is exchanged for an ID token,
   whose signature, ``iss``, ``aud``, ``exp`` and ``email_verified`` claims
   are all validated.
3. The Google account is provisioned (first login creates the user with the
   configured default role) and an internal DiffMIA access token is minted.
4. The browser is redirected to the frontend with the JWT in the URL
   fragment (``#token=...``), which is never transmitted to the server —
   a one-time exchange endpoint converts it into a normal login response.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ProviderError, ValidationError

logger = logging.getLogger("diffmia.oauth")

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_STATE_TTL_SECONDS = 600

# Tombstone store for consumed state JTIs. In-memory keyed by the JTI
# digest; TTL mirrors the state lifetime. Good enough for a single-process
# deployment and a bounded memory footprint.
_used_jti: dict[str, float] = {}

_jwks_cache: tuple[float, list[dict[str, Any]]] | None = None


def google_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


class _InvalidState(ValidationError):
    pass


# ── Signed state ──────────────────────────────────────────────────
def _state_secret() -> str:
    settings = get_settings()
    return f"{settings.secret_key}:oauth-state"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _state_sign(payload_b64: str) -> str:
    digest = hmac.new(_state_secret().encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64(digest.digest())


LOGIN_INTENT = "login"
LINK_INTENT = "link"


def make_state(client_ip: str, *, intent: str = LOGIN_INTENT, user_id: int | None = None) -> str:
    payload: dict[str, Any] = {
        "nonce": secrets.token_urlsafe(16),
        "jti": secrets.token_hex(8),
        "ip": client_ip,
        "iat": int(time.time()),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
        "intent": intent,
    }
    if user_id is not None:
        payload["uid"] = int(user_id)
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_state_sign(payload_b64)}"


def consume_state(state: str, client_ip: str) -> dict[str, Any]:
    """Verify signature, expiry, client binding and one-time use.

    Returns the signed payload so the caller can act on ``intent``/``uid``
    without trusting anything from the query string.
    """
    try:
        payload_b64, signature = state.split(".", 1)
        expected = _state_sign(payload_b64)
        if not hmac.compare_digest(expected, signature):
            raise _InvalidState("state signature mismatch")
        payload = json.loads(_unb64(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise _InvalidState("Malformed OAuth state parameter.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise _InvalidState("OAuth state has expired. Restart the sign-in flow.")
    if payload.get("ip") != client_ip:
        raise _InvalidState("OAuth state was issued for a different client.")
    jti_digest = hashlib.sha256(str(payload.get("jti", "")).encode("utf-8")).hexdigest()
    now = time.time()
    for key, issued_at in list(_used_jti.items()):
        if now - issued_at > _STATE_TTL_SECONDS:
            _used_jti.pop(key, None)
    if jti_digest in _used_jti:
        raise _InvalidState("OAuth state was already consumed.")
    _used_jti[jti_digest] = now
    return payload


# ── Google endpoints ─────────────────────────────────────────────
def build_authorize_url(redirect_uri: str, state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params, quote_via=quote)}"


#: Google's token-endpoint error codes → an actionable, non-secret explanation.
#: Every one of these used to collapse into "Google rejected the authorization
#: code.", which made a wrong client secret, an unregistered redirect URI and an
#: expired code indistinguishable without reading provider logs.
_GOOGLE_TOKEN_ERRORS: dict[str, str] = {
    "invalid_client": (
        "Google rejected this server's OAuth credentials (invalid_client). Check "
        "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then restart the backend."
    ),
    "unauthorized_client": (
        "This OAuth client may not use authorization-code sign-in "
        "(unauthorized_client). Check the client type in the Google Cloud Console."
    ),
    "redirect_uri_mismatch": (
        "Google rejected the redirect URI (redirect_uri_mismatch). Add "
        "{redirect_uri} to 'Authorized redirect URIs' (not 'Authorized "
        "JavaScript origins') for this OAuth client."
    ),
    "invalid_grant": (
        "The Google authorization code was already used, expired, or belongs to "
        "another client (invalid_grant). Start the sign-in again."
    ),
    "invalid_request": (
        "Google rejected the token request as malformed (invalid_request)."
    ),
}


def _token_error_message(error_code: str, status: int, redirect_uri: str) -> str:
    """Turn Google's error code into something a human can act on."""
    template = _GOOGLE_TOKEN_ERRORS.get(error_code)
    if template:
        return template.format(redirect_uri=redirect_uri)
    detail = f"HTTP {status}, {error_code}" if error_code else f"HTTP {status}"
    return f"Google rejected the token exchange ({detail})."


def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange the authorization code and return validated claims."""
    settings = get_settings()
    form = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        response = httpx.post(_TOKEN_ENDPOINT, data=form, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ProviderError("Could not reach Google's token endpoint.") from exc
    if response.status_code != 200:
        error_code = ""
        try:
            error_code = str(response.json().get("error") or "")
        except ValueError:
            error_code = ""
        raise ProviderError(_token_error_message(error_code, response.status_code, redirect_uri))
    body = response.json()
    id_token = body.get("id_token")
    if not id_token:
        raise ProviderError("Google token response did not contain an ID token.")
    return verify_google_id_token(id_token)


def _fetch_jwks() -> list[dict[str, Any]]:
    global _jwks_cache
    now = time.time()
    if _jwks_cache is not None and now - _jwks_cache[0] < 3600:
        return _jwks_cache[1]
    try:
        response = httpx.get(_JWKS_URI, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ProviderError("Could not reach Google's JWKS endpoint.") from exc
    if response.status_code != 200:
        raise ProviderError("Google JWKS endpoint returned an error.")
    keys = response.json().get("keys", [])
    _jwks_cache = (now, keys)
    return keys


def verify_google_id_token(token: str) -> dict[str, Any]:
    """Cryptographically validate the ID token (RS256 via JWKS) and claims."""
    try:
        encoded_header, encoded_payload, signature = token.split(".")
        header = json.loads(_unb64(encoded_header))
        payload = json.loads(_unb64(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        raise ProviderError("Malformed Google ID token.")
    if header.get("alg") != "RS256":
        raise ProviderError("Unsupported Google ID token algorithm.")
    kid = header.get("kid", "")

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    public_key: Any = None
    for key in _fetch_jwks():
        if key.get("kid") == kid:
            n = int.from_bytes(_unb64(key["n"]), "big")
            e = int.from_bytes(_unb64(key["e"]), "big")
            public_key = rsa.RSAPublicNumbers(e, n).public_key()
            break
    if public_key is None:
        raise ProviderError("Google ID token uses an unknown signing key.")
    try:
        public_key.verify(
            _unb64(signature),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise ProviderError("Google ID token signature verification failed.") from exc

    now = int(time.time())
    if payload.get("iss") not in _ISSUERS:
        raise ProviderError("Google ID token has an unexpected issuer.")
    settings = get_settings()
    audiences = payload.get("aud")
    aud_list = audiences if isinstance(audiences, list) else [audiences]
    if settings.google_client_id not in aud_list:
        raise ProviderError("Google ID token is not issued for this application.")
    if int(payload.get("exp", 0)) < now:
        raise ProviderError("Google ID token has expired.")
    if not payload.get("email_verified"):
        raise ProviderError("Google account email is not verified.")
    if not payload.get("email"):
        raise ProviderError("Google account did not share an email address.")
    if not payload.get("sub"):
        # Required: an empty subject would compare equal to the blank google_sub
        # that every local account carries, matching the wrong account entirely.
        raise ProviderError("Google account did not include a subject identifier.")
    return payload


# ── Account provisioning ─────────────────────────────────────────
def _first_matching_user(db: Any, *criteria: Any) -> Any | None:
    """Return the oldest account matching ``criteria``, tolerating duplicates.

    ``scalar_one_or_none`` raises ``MultipleResultsFound`` as soon as a row is
    duplicated, so one bad row would break sign-in for every identity that
    matched it. The partial unique index on ``google_sub`` prevents that going
    forward; a pre-existing duplicate must degrade to a logged warning rather
    than a 500.
    """
    from app.models import User

    matches = list(db.execute(select(User).where(*criteria).order_by(User.id)).scalars().all())
    if len(matches) > 1:
        logger.warning(
            "OAuth identity lookup matched %d accounts (ids=%s); using the oldest. "
            "Deduplicate the users table.",
            len(matches),
            [m.id for m in matches],
        )
    return matches[0] if matches else None


def get_or_create_google_user(claims: dict[str, Any], db: Any) -> Any:
    from app.core.exceptions import PermissionDeniedError
    from app.models import User
    from app.models.enums import UserRole

    email = str(claims["email"]).strip().lower()
    sub = str(claims.get("sub") or "")
    if not sub:
        # Fail closed rather than provisioning an account that can never be
        # matched again (a google_provider row with no subject).
        raise ProviderError("Google did not return a subject identifier.")

    # Scoped by subject first; an empty subject would otherwise match the blank
    # google_sub that every local account carries.
    user = _first_matching_user(db, User.google_sub == sub)
    if user is None:
        user = _first_matching_user(db, User.email == email)
    if user is not None:
        if not user.is_active:
            raise PermissionDeniedError("Account is disabled.")
        # Bind the Google identity. Local accounts keep password login.
        # Google has already validated the email, so the linkage also
        # satisfies email verification.
        user.google_sub = sub
        user.email_verified = True
        db.add(user)
        return user

    settings = get_settings()
    base = email.split("@", 1)[0] or "google-user"
    username = base
    suffix = 1
    while db.execute(select(User).where(User.username == username)).scalar_one_or_none() is not None:
        suffix += 1
        username = f"{base}-{suffix}"
    role = settings.oauth_default_role.upper()
    if role not in {r.value for r in UserRole}:
        role = UserRole.VIEWER.value
    user = User(
        username=username,
        email=email,
        password_hash="",
        auth_provider="google",
        google_sub=sub,
        role=role,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


# ── Linking a Google identity to an existing account ─────────────
def attach_google_identity(claims: dict[str, Any], user: Any, db: Any) -> None:
    """Attach Google claims to an already signed-in account (Settings page).

    Idempotent for the same Google account, and refuses to steal an identity
    that belongs to somebody else. The account's own email is never replaced:
    linking only marks it verified when Google vouched for the same address.
    """
    from app.core.exceptions import ConflictError, ValidationError
    from app.models import User

    sub = str(claims.get("sub") or "")
    if not sub:
        raise ValidationError("Google did not return an account identifier.")

    # Checked against every holder, not just the first: with a duplicated subject
    # `scalar_one_or_none` would raise, and a single-row peek could miss a real
    # conflict. Any *other* account holding this subject is a refusal.
    other_ids = [
        row.id
        for row in db.execute(select(User).where(User.google_sub == sub)).scalars().all()
        if row.id != user.id
    ]
    if other_ids:
        raise ConflictError(
            "That Google account is already linked to another DiffMIA account.",
            code="GOOGLE_ALREADY_LINKED",
        )
    if user.google_sub and user.google_sub != sub:
        raise ConflictError(
            "This account is already linked to a different Google account.",
            code="GOOGLE_LINK_CONFLICT",
        )

    user.google_sub = sub
    google_email = str(claims.get("email") or "").strip().lower()
    if google_email and google_email == (user.email or "").strip().lower():
        # Google proved control of this exact address.
        user.email_verified = True
    if not user.password_hash:
        user.auth_provider = "google"
    db.add(user)


def detach_google_identity(user: Any, db: Any) -> None:
    """Remove the Google link, refusing to leave an account with no way in."""
    from app.core.exceptions import ValidationError

    if not user.google_sub:
        raise ValidationError("This account has no Google account linked.", code="GOOGLE_NOT_LINKED")
    if not user.password_hash:
        raise ValidationError(
            "This account signs in only with Google. Set a password first, or you would be locked out.",
            code="GOOGLE_UNLINK_BLOCKED",
        )
    user.google_sub = ""
    user.auth_provider = "local"
    db.add(user)
