"""Password reset flow tests (forgot-password -> reset-password)."""
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
    get_settings.cache_clear()
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def _register(client, username, email):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": "sup3rsecret!", "email": email},
    )


def _forgot(client, email):
    return client.post("/api/auth/forgot-password", json={"email": email})


def _reset(client, token, new_password="n3w-password!"):
    return client.post("/api/auth/reset-password", json={"token": token, "new_password": new_password})


def test_forgot_password_returns_development_token(client, registration_on):
    _register(client, "resetme", "reset@example.com")
    response = _forgot(client, "reset@example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body.get("development_token"), "dev token expected without SMTP outside production"


def test_forgot_password_uniform_response_for_unknown_email(client, registration_on):
    response = _forgot(client, "nobody@example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert "development_token" not in body  # no token -> account existence not disclosed


def test_forgot_password_never_discloses_seeded_accounts(client):
    # The seeded admin has an email too — the response must look identical.
    response = _forgot(client, "admin@diffmia.local")
    assert response.status_code == 200
    assert response.json()["status"] == "sent"


def test_reset_password_changes_the_credential(client, registration_on):
    _register(client, "changer", "changer@example.com")
    token = _forgot(client, "changer@example.com").json()["development_token"]
    assert _reset(client, token).status_code == 200

    old_login = client.post("/api/auth/login", json={"username": "changer", "password": "sup3rsecret!"})
    assert old_login.status_code == 401
    new_login = client.post("/api/auth/login", json={"username": "changer", "password": "n3w-password!"})
    assert new_login.status_code == 200


def test_reset_token_is_single_use(client, registration_on):
    _register(client, "oncereset", "oncereset@example.com")
    token = _forgot(client, "oncereset@example.com").json()["development_token"]
    assert _reset(client, token).status_code == 200
    replay = _reset(client, token, "another-pass-1!")
    assert replay.status_code == 422


def test_reset_password_rejects_short_password(client, registration_on):
    _register(client, "shortpw", "shortpw@example.com")
    token = _forgot(client, "shortpw@example.com").json()["development_token"]
    response = _reset(client, token, "short")
    assert response.status_code == 422
    # The consumed-but-failed token stays usable (nothing was cleared).
    assert _reset(client, token).status_code == 200


def test_reset_password_rejects_garbage_token(client):
    response = _reset(client, "garbage.token.value")
    assert response.status_code == 422


def test_email_verify_token_cannot_reset_password(client, registration_on):
    # Cross-type token usage must be rejected (typ claim mismatch).
    get_settings.cache_clear()
    monkeypatch_enabled = get_settings
    from app.core.mailer import mint_token
    from app.db.session import get_session_factory
    from sqlalchemy import select

    from app.models import User

    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        wrong_type = mint_token("email_verify", user.id)
    finally:
        session.close()
    response = _reset(client, wrong_type)
    assert response.status_code == 422


def test_reset_flow_for_google_only_account(client, registration_on):
    """A Google-linked account has no local password; reset must not 500 and
    must still respond uniformly (it links by google_sub, so it's allowed)."""
    _register(client, "googleish", "googleish@example.com")
    token = _forgot(client, "googleish@example.com").json()["development_token"]
    assert _reset(client, token).status_code == 200
