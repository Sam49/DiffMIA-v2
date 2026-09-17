"""Self-service registration + email verification tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def registration_on(monkeypatch):
    """Enable registration WITH the email-verification gate (settings are cached)."""
    get_settings.cache_clear()
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture()
def verification_off(monkeypatch):
    """Disable the email-verification gate (self-registration tests only)."""
    get_settings.cache_clear()
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _register(client, username="newuser", password="sup3rsecret!", email="new@example.com"):
    return client.post("/api/auth/register", json={"username": username, "password": password, "email": email})


def _dev_token(register_response) -> str:
    token = register_response.json()["verification"]["development_token"]
    assert token, "expected a development verification token in the test environment"
    return token


# ── Toggle behaviour ──────────────────────────────────────────────
def test_registration_disabled_by_default(client):
    response = _register(client)
    assert response.status_code == 403
    assert response.json()["error"] == "PERMISSION_DENIED"
    status = client.get("/api/auth/registration/status").json()
    assert status["registration_enabled"] is False


def test_oauth_status_reports_flags(client, registration_on):
    status = client.get("/api/auth/oauth/status").json()
    assert status["self_registration"] is True
    assert status["email_verification_required"] is True


# ── Registration with verification (default) ─────────────────────
def test_registration_success_when_enabled(client, registration_on):
    response = _register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["user"]["username"] == "newuser"
    assert body["user"]["role"] == "VIEWER"
    assert body["user"]["email_verified"] is False
    assert body["verification"]["required"] is True
    # Token minted at registration, but the account is unverified: EVERY
    # authenticated endpoint must reject it (401 EMAIL_NOT_VERIFIED).
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 401
    assert me.json()["error"] == "EMAIL_NOT_VERIFIED"


def test_unverified_user_cannot_log_in(client, registration_on):
    assert _register(client, username="gatecheck", email="gate@example.com").status_code == 201
    login = client.post("/api/auth/login", json={"username": "gatecheck", "password": "sup3rsecret!"})
    assert login.status_code == 401
    assert login.json()["error"] == "EMAIL_NOT_VERIFIED"


def test_verify_email_flow(client, registration_on):
    body = _register(client, username="verifyflow", email="verify@example.com").json()
    token = _dev_token_register(body)
    assert body["user"]["email_verified"] is False

    verified = client.post("/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True

    login = client.post("/api/auth/login", json={"username": "verifyflow", "password": "sup3rsecret!"})
    assert login.status_code == 200


def _dev_token_register(body) -> str:
    token = body["verification"]["development_token"]
    assert token, "expected development verification token"
    return token


def test_verify_email_token_is_single_use(client, registration_on):
    token = _dev_token_register(_register(client, username="onetime", email="onetime@example.com").json())
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    replay = client.post("/api/auth/verify-email", json={"token": token})
    assert replay.status_code == 422


def test_verify_email_rejects_garbage_token(client):
    response = client.post("/api/auth/verify-email", json={"token": "not-a-real-token"})
    assert response.status_code == 422


def test_public_resend_by_email_replaces_old_token(client, registration_on):
    body = _register(client, username="resendme", email="resend@example.com").json()
    old_token = _dev_token_register(body)
    resend = client.post("/api/auth/resend-verification-email", json={"email": "resend@example.com"})
    assert resend.status_code == 200
    new_token = resend.json()["development_token"]
    assert new_token and new_token != old_token
    # The old link is dead (hash slot overwritten); the new one works.
    assert client.post("/api/auth/verify-email", json={"token": old_token}).status_code == 422
    assert client.post("/api/auth/verify-email", json={"token": new_token}).status_code == 200


def test_public_resend_uniform_for_unknown_or_verified(client, registration_on):
    # Unknown email: uniform response, no token.
    response = client.post("/api/auth/resend-verification-email", json={"email": "ghost@example.com"})
    assert response.status_code == 200
    assert "development_token" not in response.json()
    # Verified account: also uniform, no token (nothing left to verify).
    body = _register(client, username="alreadyok", email="alreadyok@example.com").json()
    assert client.post("/api/auth/verify-email", json={"token": _dev_token_register(body)}).status_code == 200
    settled = client.post("/api/auth/resend-verification-email", json={"email": "alreadyok@example.com"})
    assert settled.status_code == 200
    assert "development_token" not in settled.json()


# ── Registration without verification gate ───────────────────────
def test_registration_without_verification_signs_in_immediately(client, verification_off):
    response = _register(client)
    assert response.status_code == 201
    assert response.json()["user"]["email_verified"] is True
    assert response.json()["verification"] is None
    login = client.post("/api/auth/login", json={"username": "newuser", "password": "sup3rsecret!"})
    assert login.status_code == 200


# ── Duplicate / validation behaviour ─────────────────────────────
def test_registration_duplicate_username_and_email(client, verification_off):
    assert _register(client).status_code == 201
    dup_username = _register(client, username="newuser", email="other@example.com")
    assert dup_username.status_code == 409
    assert "already taken" in dup_username.json()["message"]
    dup_email = _register(client, username="other", email="new@example.com")
    assert dup_email.status_code == 409
    assert "email" in dup_email.json()["message"]
    # Case-insensitive email uniqueness.
    dup_case = _register(client, username="third", email="NEW@EXAMPLE.COM")
    assert dup_case.status_code == 409


def test_registration_rejects_weak_password(client, verification_off):
    assert _register(client, password="short").status_code == 422


def test_registration_rejects_invalid_username(client, verification_off):
    assert _register(client, username="bad user!", email="bad@example.com").status_code == 422


def test_registration_requires_email(client, verification_off):
    response = client.post(
        "/api/auth/register", json={"username": "noemail", "password": "sup3rsecret!"}
    )
    assert response.status_code == 422


def test_admin_cannot_create_admin_via_api(client, admin_headers):
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "sneaky", "password": "sup3rsecret!", "role": "ADMIN"},
    )
    assert response.status_code == 422
