"""Credential-free sign-in (`POST /auth/auto-login`).

The route mints a real session for a configured account so an installation can
run without a login page. These tests pin what makes that safe: it is inert
unless AUTO_LOGIN_ENABLED is set, and it refuses accounts that could not use a
session anyway (missing, disabled, unverified).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

ENDPOINT = "/api/auth/auto-login"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _configure(monkeypatch, *, enabled: bool = True, username: str = "admin") -> None:
    """Settings are cached, so patch the object the routes read."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_login_enabled", enabled)
    monkeypatch.setattr(settings, "auto_login_username", username)


def _session():
    from app.db.session import get_session_factory

    return get_session_factory()()


def _update(username: str, **fields) -> None:
    from sqlalchemy import select

    from app.models import User

    session = _session()
    try:
        user = session.execute(select(User).where(User.username == username)).scalar_one()
        for key, value in fields.items():
            setattr(user, key, value)
        session.commit()
    finally:
        session.close()


def test_disabled_by_default_is_inert(client, monkeypatch):
    """A publicly reachable deployment must never be enterable anonymously."""
    _configure(monkeypatch, enabled=False)
    response = client.post(ENDPOINT)
    assert response.status_code == 403
    assert response.json()["error"] == "PERMISSION_DENIED"
    assert "access_token" not in response.text


def test_enabled_issues_a_working_admin_session(client, monkeypatch):
    _configure(monkeypatch)
    response = client.post(ENDPOINT)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "ADMIN"
    assert "password_hash" not in response.text

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["username"] == "admin"
    # A real admin session, not just a readable token.
    assert client.get("/api/users", headers=headers).status_code == 200


def test_missing_account_is_rejected_with_its_name(client, monkeypatch):
    _configure(monkeypatch, username="ghost")
    response = client.post(ENDPOINT)
    assert response.status_code == 401
    assert "ghost" in response.json()["message"]
    assert "access_token" not in response.text


def test_disabled_account_is_rejected(client, monkeypatch):
    _configure(monkeypatch)
    _update("admin", is_active=False)
    response = client.post(ENDPOINT)
    assert response.status_code == 401
    assert "disabled" in response.json()["message"]
    assert "access_token" not in response.text


def test_unverified_account_is_rejected(client, monkeypatch):
    """Otherwise a token would be minted only to be refused by every endpoint."""
    _configure(monkeypatch)
    _update("admin", email_verified=False)
    response = client.post(ENDPOINT)
    assert response.status_code == 401
    assert response.json()["error"] == "EMAIL_NOT_VERIFIED"
    assert "access_token" not in response.text


def test_any_local_account_can_be_configured(client, monkeypatch):
    from app.models import User

    session = _session()
    try:
        session.add(
            User(username="lab", email="lab@example.com", password_hash="", role="VIEWER")
        )
        session.commit()
    finally:
        session.close()

    _configure(monkeypatch, username="lab")
    response = client.post(ENDPOINT)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "VIEWER"
