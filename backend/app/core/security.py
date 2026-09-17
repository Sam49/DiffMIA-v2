"""Security primitives: password hashing + signed access tokens (HS256 JWT).

PBKDF2-HMAC-SHA256 is used for password storage (stdlib only, no C
extensions required). Tokens are standard JSON Web Tokens signed with
HMAC-SHA256 using the configured SECRET_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.exceptions import AuthenticationError

PBKDF2_ITERATIONS = 600_000
_ALG = "HS256"


# ── Password hashing ──────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


# ── Token primitives ──────────────────────────────────────────────
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(data: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()


def create_access_token(payload: dict[str, Any], secret: str, expires_minutes: int) -> str:
    body = dict(payload)
    now = int(time.time())
    body.setdefault("iat", now)
    body.setdefault("exp", now + expires_minutes * 60)
    if "jti" not in body:
        body["jti"] = secrets.token_hex(8)
    header = {"alg": _ALG, "typ": "JWT"}
    encoded_header = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = _b64(_sign(signing_input, secret))
    return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError:
        raise AuthenticationError("Invalid token format")
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected = _b64(_sign(signing_input, secret))
    if not hmac.compare_digest(expected, signature):
        raise AuthenticationError("Invalid or tampered token")
    try:
        payload = json.loads(_unb64(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        raise AuthenticationError("Invalid token payload")
    exp = payload.get("exp", 0)
    if int(exp) < int(time.time()):
        raise AuthenticationError("Token has expired")
    return payload
