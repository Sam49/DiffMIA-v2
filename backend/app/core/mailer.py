"""Account-action tokens and outbound email.

Two token types, both HMAC-signed (bound to SECRET_KEY), single-use (the SHA-256
hash is stored on the user row — a database leak cannot replay a link) and
time-limited. The single ``password_reset_token_hash`` slot stores whichever
token is currently outstanding (verification or reset), which keeps both flows
one-use by construction:

- Email verification: minted at self-registration and re-mintable via the
  resend endpoints; consuming it flips ``email_verified``.
- Password reset: minted by the forgot-password endpoint for any account with
  a usable credential (local password or Google linkage).

Delivery: SMTP when ``SMTP_HOST`` is configured; otherwise the message is
logged and, outside production, the token is surfaced to the caller so
developer flows can complete without a mail server.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Literal

from fastapi import Request
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ProviderError, RateLimitError, ValidationError
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import hash_password
from app.models import User

logger = logging.getLogger("diffmia.mailer")

TokenType = Literal["email_verify", "password_reset"]

_email_limiter = SlidingWindowLimiter(max_requests=10)


def _secret() -> bytes:
    return f"{get_settings().secret_key}:account-actions".encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hash(candidate: str) -> str:
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()


def _sign(payload_b64: str) -> str:
    return _b64(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())


def _ttl_minutes(token_type: TokenType) -> int:
    settings = get_settings()
    if token_type == "email_verify":
        return settings.email_verification_token_ttl_minutes
    return settings.password_reset_token_ttl_minutes


def mint_token(token_type: TokenType, user_id: int) -> str:
    ttl = _ttl_minutes(token_type)
    now = int(time.time())
    payload = {"typ": token_type, "sub": user_id, "iat": now, "exp": now + ttl * 60, "nonce": secrets.token_hex(8)}
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def decode_token(token: str, expected_type: TokenType) -> int:
    """Validate signature, type and expiry; return the user id."""
    try:
        payload_b64, signature = token.split(".", 1)
        if not hmac.compare_digest(_sign(payload_b64), signature):
            raise ValueError("signature mismatch")
        payload = json.loads(_unb64(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise ValidationError("This link is invalid or has already been used.")
    if payload.get("typ") != expected_type:
        raise ValidationError("This link is invalid for this action.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValidationError("This link has expired. Please request a new one.")
    return int(payload.get("sub", 0))


# ── Account actions ───────────────────────────────────────────────
def _user_by_email(db: Any, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _has_usable_credential(user: User) -> bool:
    return bool(user.password_hash) or bool(user.google_sub)


def _check_outstanding_token(user: User, token: str) -> None:
    """The stored hash must match AND the stored expiry must be in the future."""
    if user.password_reset_token_hash != _hash(token):
        raise ValidationError("This link is invalid or has already been used.")
    expires = user.password_reset_expires_at
    if expires is not None:
        if expires.tzinfo is None:  # SQLite returns naive datetimes
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise ValidationError("This link has expired. Please request a new one.")


def _issue_email_token(db: Any, user: User, token_type: TokenType) -> dict[str, Any]:
    """Mint + store + deliver an account-action email; shared response shape."""
    settings = get_settings()
    token = mint_token(token_type, user.id)
    user.password_reset_token_hash = _hash(token)
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=_ttl_minutes(token_type)
    )
    db.add(user)
    if token_type == "email_verify":
        body = _render_email(
            greeting=f"Hi {user.username},",
            paragraphs=[
                "Please confirm your email address to activate your DiffMIA account.",
                "This link is valid for 24 hours and can be used once.",
            ],
            button_label="Verify email",
            url=_frontend_url(f"/verify-email?token={token}"),
            footer="If you didn't create a DiffMIA account, you can ignore this email.",
        )
        delivered = _send(user.email, "Verify your DiffMIA account", body)
    else:
        body = _render_email(
            greeting=f"Hi {user.username},",
            paragraphs=[
                "We received a request to reset your DiffMIA password.",
                f"This link is valid for {_ttl_minutes(token_type)} minutes and can be used once.",
            ],
            button_label="Choose a new password",
            url=_frontend_url(f"/reset-password?token={token}"),
            footer="If you didn't request a reset, you can safely ignore this email.",
        )
        delivered = _send(user.email, "Reset your DiffMIA password", body)
    response: dict[str, Any] = {"status": "sent"}
    # Without SMTP (logged-only delivery) and outside production, the token is
    # returned so the flow is testable without a mail server.
    if delivered is not None and settings.app_env != "production":
        response["development_token"] = token
    return response


def request_verification_email(db: Any, user: User) -> dict[str, Any]:
    """Mint a fresh verification token, store its hash, and send the email."""
    return _issue_email_token(db, user, "email_verify")


def request_password_reset(db: Any, email: str, request: Request) -> dict[str, Any]:
    """Public forgot-password endpoint logic. Always returns a uniform body."""
    client = request.client.host if request.client else "unknown"
    if not _email_limiter.allow(f"pwreset:{client}"):
        raise RateLimitError("Too many reset requests. Try again later.")

    user = _user_by_email(db, email.strip().lower())
    if user is None or not user.is_active or not _has_usable_credential(user):
        # Uniform response: never disclose whether the account exists.
        return {"status": "sent"}
    return _issue_email_token(db, user, "password_reset")


def request_verification_by_email(db: Any, email: str, request: Request) -> dict[str, Any]:
    """Public resend for unverified accounts (they cannot sign in to use the
    authenticated resend). Uniform response; the email must belong to an
    existing, active, unverified local account, so this cannot be used to
    spam arbitrary addresses."""
    client = request.client.host if request.client else "unknown"
    if not _email_limiter.allow(f"verify:{client}"):
        raise RateLimitError("Too many requests. Try again later.")

    user = _user_by_email(db, email.strip().lower())
    if user is None or not user.is_active or user.email_verified or not user.password_hash:
        return {"status": "sent"}
    return _issue_email_token(db, user, "email_verify")


def confirm_email_verification(db: Any, token: str) -> User:
    user_id = decode_token(token, "email_verify")
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Account no longer exists.")
    _check_outstanding_token(user, token)
    user.email_verified = True
    user.password_reset_token_hash = ""
    user.password_reset_expires_at = None
    db.add(user)
    return user


def reset_password(db: Any, token: str, new_password: str) -> User:
    user_id = decode_token(token, "password_reset")
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Account no longer exists.")
    _check_outstanding_token(user, token)
    if len(new_password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    user.password_hash = hash_password(new_password)
    user.password_reset_token_hash = ""
    user.password_reset_expires_at = None
    db.add(user)
    return user


# ── Email rendering / delivery ────────────────────────────────────
def _frontend_url(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


def _render_email(*, greeting: str, paragraphs: list[str], button_label: str, url: str, footer: str) -> str:
    return (
        f"{greeting}\n\n"
        + "\n\n".join(paragraphs)
        + f"\n\n{button_label}:\n{url}\n\n{footer}\n"
    )


def _send(to: str, subject: str, body: str) -> str | None:
    """Send via SMTP when configured; otherwise log and return the body."""
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if not settings.smtp_host:
        logger.info("SMTP not configured; email to %s logged:\n%s", to, body)
        return body
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        raise ProviderError("Could not send the email. Please try again later.") from exc
    return None
