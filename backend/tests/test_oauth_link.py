"""Linking a Google identity to an existing account.

Covers the Settings-initiated flow: an authenticated start endpoint that binds
the account into a signed state, the callback branch that attaches the Google
identity (including conflicts), and unlinking. Google itself is never called —
the code exchange is stubbed at the route seam.
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.google_oauth import LINK_INTENT, make_state
from app.main import app

FRONTEND = "http://localhost:5173"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _configure_google(monkeypatch, enabled: bool = True) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com" if enabled else "")
    monkeypatch.setattr(settings, "google_client_secret", "secret" if enabled else "")


def _session():
    from app.db.session import get_session_factory

    return get_session_factory()()


def _admin_id() -> int:
    from app.models import User

    session = _session()
    try:
        return session.execute(select(User).where(User.username == "admin")).scalar_one().id
    finally:
        session.close()


def _user_row(username: str):
    from app.models import User

    session = _session()
    try:
        return session.execute(select(User).where(User.username == username)).scalar_one()
    finally:
        session.close()


def _state_payload(state: str) -> dict:
    payload_b64 = state.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))


def test_link_start_requires_authentication(client):
    response = client.post("/api/auth/google/link/start")
    assert response.status_code == 401


def test_link_start_requires_google_configuration(client, admin_headers, monkeypatch):
    _configure_google(monkeypatch, enabled=False)
    response = client.post("/api/auth/google/link/start", headers=admin_headers)
    assert response.status_code == 422
    assert response.json()["error"] == "OAUTH_NOT_CONFIGURED"


def test_link_start_returns_consent_url_bound_to_the_account(client, admin_headers, monkeypatch):
    _configure_google(monkeypatch)
    response = client.post("/api/auth/google/link/start", headers=admin_headers)
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "cid.apps.googleusercontent.com" in url

    state = url.split("state=", 1)[1].split("&", 1)[0]
    payload = _state_payload(state)
    assert payload["intent"] == LINK_INTENT
    assert payload["uid"] == _admin_id()


def test_callback_links_google_to_the_signed_in_account(client, admin_headers, monkeypatch):
    _configure_google(monkeypatch)
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes,
        "exchange_code",
        lambda code, redirect_uri: {
            "sub": "google-sub-abc",
            "email": "admin@diffmia.local",  # matches the account address
            "email_verified": True,
        },
    )
    state = make_state("testclient", intent=LINK_INTENT, user_id=_admin_id())
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/settings#google=linked"

    admin = _user_row("admin")
    assert admin.google_sub == "google-sub-abc"
    # The address matched, so Google vouched for it.
    assert admin.email_verified is True

    # The API reports the link without leaking the raw subject.
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["google_linked"] is True
    assert "google-sub-abc" not in json.dumps(me)


def test_link_refuses_an_identity_owned_by_another_account(client, admin_headers, monkeypatch):
    from app.models import User

    _configure_google(monkeypatch)
    import app.api.routes.auth as auth_routes

    session = _session()
    session.add(User(username="other-user", email="other@example.com", password_hash="x", role="VIEWER",
                     google_sub="google-sub-taken"))
    session.commit()
    session.close()

    monkeypatch.setattr(
        auth_routes,
        "exchange_code",
        lambda code, redirect_uri: {"sub": "google-sub-taken", "email": "other@example.com"},
    )
    state = make_state("testclient", intent=LINK_INTENT, user_id=_admin_id())
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "google_error=GOOGLE_ALREADY_LINKED" in response.headers["location"]
    assert _user_row("admin").google_sub == ""


def test_link_flow_with_a_deleted_account_fails_closed(client, monkeypatch):
    _configure_google(monkeypatch)
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes, "exchange_code", lambda code, redirect_uri: {"sub": "s", "email": "x@example.com"}
    )
    state = make_state("testclient", intent=LINK_INTENT, user_id=999_999)
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert "google_error=OAUTH_FAILED" in response.headers["location"]


def test_login_intent_still_signs_in(client, monkeypatch):
    """The link branch must not capture ordinary sign-ins."""
    _configure_google(monkeypatch)
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes,
        "exchange_code",
        lambda code, redirect_uri: {"sub": "sign-in-sub", "email": "fresh@example.com", "email_verified": True},
    )
    state = make_state("testclient")  # default intent: login
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{FRONTEND}/oauth/callback#token=")
    assert _user_row("fresh") is not None


def test_unlink_removes_the_link(client, admin_headers, monkeypatch):
    _configure_google(monkeypatch)
    import app.api.routes.auth as auth_routes

    monkeypatch.setattr(
        auth_routes,
        "exchange_code",
        lambda code, redirect_uri: {"sub": "google-sub-unlink", "email": "admin@diffmia.local"},
    )
    state = make_state("testclient", intent=LINK_INTENT, user_id=_admin_id())
    client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _user_row("admin").google_sub == "google-sub-unlink"

    response = client.post("/api/auth/google/unlink", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["google_linked"] is False
    assert _user_row("admin").google_sub == ""

    # Unlinking twice reports the state honestly rather than silently passing.
    again = client.post("/api/auth/google/unlink", headers=admin_headers)
    assert again.status_code == 422
    assert again.json()["error"] == "GOOGLE_NOT_LINKED"


def test_unlink_requires_authentication(client):
    assert client.post("/api/auth/google/unlink").status_code == 401


def test_unlink_is_blocked_for_google_only_accounts(client, admin_headers, monkeypatch):
    """A password-less account must not be able to lock itself out."""
    from app.models import User

    session = _session()
    session.add(
        User(username="g-only", email="g@example.com", password_hash="", role="VIEWER",
             auth_provider="google", google_sub="google-sub-only")
    )
    session.commit()
    session.close()

    token_headers = _token_for("g-only")
    response = client.post("/api/auth/google/unlink", headers=token_headers)
    assert response.status_code == 422
    assert response.json()["error"] == "GOOGLE_UNLINK_BLOCKED"
    assert _user_row("g-only").google_sub == "google-sub-only"


def _token_for(username: str) -> dict:
    from app.core.config import get_settings
    from app.core.security import create_access_token
    from app.models import User

    session = _session()
    try:
        user = session.execute(select(User).where(User.username == username)).scalar_one()
        token = create_access_token(
            {"sub": str(user.id), "username": user.username, "role": user.role},
            get_settings().secret_key,
            60,
        )
    finally:
        session.close()
    return {"Authorization": f"Bearer {token}"}
