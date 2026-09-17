"""Google OAuth flow tests.

Covers: status endpoint, signed state verification, provisioning logic,
handoff-token exchange, and the callback's error paths. Network calls to
Google are NOT made; the exchange step is exercised through unit seams.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.core.google_oauth import (
    _state_secret,
    consume_state,
    get_or_create_google_user,
    make_state,
)
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _sign(payload_b64: str) -> str:
    digest = hmac.new(_state_secret().encode(), payload_b64.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).decode().rstrip("=")


def _google_disabled(monkeypatch) -> None:
    """Force the unconfigured state so these tests hold on any developer machine."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")


def test_oauth_status_reports_disabled_by_default(client, monkeypatch):
    _google_disabled(monkeypatch)
    response = client.get("/api/auth/oauth/status")
    assert response.status_code == 200
    assert response.json() == {
        "google_enabled": False,
        "self_registration": False,
        "email_verification_required": False,
    }


def test_oauth_authorize_requires_configuration(client, monkeypatch):
    _google_disabled(monkeypatch)
    response = client.get("/api/auth/google/authorize", follow_redirects=False)
    assert response.status_code == 422
    assert response.json()["error"] == "OAUTH_NOT_CONFIGURED"


def test_state_roundtrip_and_client_binding():
    state = make_state("1.2.3.4")
    consume_state(state, "1.2.3.4")  # ok
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        consume_state(state, "5.6.7.8")  # wrong IP


def test_state_replay_is_rejected():
    from app.core.exceptions import ValidationError

    state = make_state("1.2.3.4")
    consume_state(state, "1.2.3.4")
    with pytest.raises(ValidationError):
        consume_state(state, "1.2.3.4")  # replay


def test_state_tamper_is_rejected():
    from app.core.exceptions import ValidationError

    payload = base64.urlsafe_b64encode(
        json.dumps({"jti": "x", "exp": int(time.time()) + 60, "ip": "1.1.1.1"}).encode()
    ).decode().rstrip("=")
    bad = f"{payload}.AAAA"
    with pytest.raises(ValidationError):
        consume_state(bad, "1.1.1.1")


def test_provisioning_creates_google_user(db_session):
    from sqlalchemy import select

    from app.models import User

    claims = {"email": "Ada.Lovelace@example.com", "sub": "sub-123", "email_verified": True}
    user = get_or_create_google_user(claims, db_session)
    db_session.commit()
    assert user.username == "ada.lovelace"  # derived from the lowercased email
    assert user.email == "ada.lovelace@example.com"
    assert user.auth_provider == "google"
    assert user.google_sub == "sub-123"
    assert user.role == get_settings().oauth_default_role.upper()

    again = get_or_create_google_user(claims, db_session)
    assert again.id == user.id

    # Existing local account with the same email is linked, not duplicated.
    local = User(username="local-pat", email="pat@example.com", password_hash="x", role="VIEWER")
    db_session.add(local)
    db_session.commit()
    linked = get_or_create_google_user({"email": "pat@example.com", "sub": "sub-999"}, db_session)
    db_session.commit()
    assert linked.id == local.id
    assert linked.google_sub == "sub-999"
    assert linked.password_hash == "x"  # local login keeps working
    total = len(db_session.execute(select(User)).scalars().all())
    assert total == 3  # admin + google user + linked local account, no dupes


def test_provisioning_requires_a_subject_and_never_matches_local_accounts(db_session):
    """An empty Google subject must not match the blank google_sub of every local account."""
    from sqlalchemy import select

    from app.models import User

    admin = db_session.execute(select(User).where(User.username == "admin")).scalar_one()
    assert admin.google_sub == ""  # local accounts carry an empty subject

    with pytest.raises(ProviderError):
        get_or_create_google_user({"email": "admin@example.com"}, db_session)

    db_session.refresh(admin)
    assert admin.google_sub == ""
    assert admin.username == "admin"


def test_provisioning_tolerates_duplicate_rows_instead_of_raising(db_session):
    """A duplicated row must degrade to a warning, not MultipleResultsFound."""
    from sqlalchemy import select

    from app.models import User

    # Email is not uniquely constrained, so this state is representable.
    db_session.add_all(
        [
            User(username="dupe-a", email="dupe@example.com", password_hash="x", role="VIEWER"),
            User(username="dupe-b", email="dupe@example.com", password_hash="x", role="VIEWER"),
        ]
    )
    db_session.commit()

    user = get_or_create_google_user({"email": "dupe@example.com", "sub": "sub-dupe"}, db_session)
    db_session.commit()
    assert user.username == "dupe-a"  # oldest wins, deterministically
    assert user.google_sub == "sub-dupe"

    db_session.add(
        User(username="dupe-c", email="orphan@example.com", password_hash="", auth_provider="google", role="VIEWER")
    )
    db_session.commit()
    orphan_row = db_session.execute(select(User).where(User.username == "dupe-c")).scalar_one()
    # A google-flagged account that lost its subject is recovered in place by email.
    fixed = get_or_create_google_user({"email": "orphan@example.com", "sub": "sub-orphan"}, db_session)
    db_session.commit()
    assert fixed.id == orphan_row.id
    assert fixed.google_sub == "sub-orphan"
    assert fixed.auth_provider == "google"


def test_one_account_per_google_identity_is_enforced(db_session):
    """google_sub is unique when set, but many blank subjects remain legal."""
    from sqlalchemy.exc import IntegrityError

    from app.models import User

    db_session.add(
        User(
            username="g-one",
            email="one@example.com",
            password_hash="",
            auth_provider="google",
            google_sub="shared-sub",
            role="VIEWER",
        )
    )
    db_session.commit()
    db_session.add(
        User(
            username="g-two",
            email="two@example.com",
            password_hash="",
            auth_provider="google",
            google_sub="shared-sub",
            role="VIEWER",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Several local accounts with no subject must still be insertable (partial index).
    db_session.add_all(
        [
            User(username="l-one", email="l1@example.com", password_hash="x", role="VIEWER"),
            User(username="l-two", email="l2@example.com", password_hash="x", role="VIEWER"),
        ]
    )
    db_session.commit()


def test_handoff_exchange_flow(client):
    from sqlalchemy import select

    from app.core.security import create_access_token
    from app.db.session import get_session_factory
    from app.models import User

    session = get_session_factory()()
    user = session.execute(select(User).where(User.username == "admin")).scalar_one()
    session.close()

    handoff = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role, "typ": "oauth_handoff"},
        get_settings().secret_key,
        2,
    )
    response = client.post("/api/auth/oauth/exchange", headers={"Authorization": f"Bearer {handoff}"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["username"] == "admin"

    # A normal login token must NOT be exchangeable (typ mismatch).
    normal = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role},
        get_settings().secret_key,
        60,
    )
    denied = client.post("/api/auth/oauth/exchange", headers={"Authorization": f"Bearer {normal}"})
    assert denied.status_code == 401


def test_callback_error_redirects_to_frontend(client):
    response = client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied", "state": make_state("testclient")},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "/login?oauth_error=OAUTH_CANCELLED" in location


def test_callback_with_bad_state_fails_gracefully(client):
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "abc", "state": "not-a-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    # A rejected state is reported distinctly from a failed token exchange, so the
    # user learns whether to retry the sign-in or check the server configuration.
    assert "oauth_error=OAUTH_STATE_INVALID" in response.headers["location"]


class _FakeTokenResponse:
    """Minimal stand-in for a Google token-endpoint response."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.mark.parametrize(
    ("google_error", "expected_fragments"),
    [
        ("invalid_client", ["invalid_client", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]),
        ("invalid_grant", ["invalid_grant", "Start the sign-in again"]),
        (
            "redirect_uri_mismatch",
            ["redirect_uri_mismatch", "Authorized redirect URIs", "localhost:8000"],
        ),
        ("something_new", ["something_new", "HTTP 401"]),
    ],
)
def test_exchange_code_explains_googles_error_code(monkeypatch, google_error, expected_fragments):
    """The specific cause must survive, not collapse into one generic sentence."""
    from app.core import google_oauth

    monkeypatch.setattr(
        google_oauth.httpx,
        "post",
        lambda *a, **kw: _FakeTokenResponse(401, {"error": google_error}),
    )
    with pytest.raises(ProviderError) as excinfo:
        google_oauth.exchange_code("a-code", "http://localhost:8000/api/auth/google/callback")
    message = str(excinfo.value)
    for fragment in expected_fragments:
        assert fragment in message, f"{fragment!r} missing from {message!r}"


def test_exchange_code_tolerates_a_non_json_error_body(monkeypatch):
    from app.core import google_oauth

    class _BadBody(_FakeTokenResponse):
        def json(self):
            raise ValueError("no json")

    monkeypatch.setattr(google_oauth.httpx, "post", lambda *a, **kw: _BadBody(503, {}))
    with pytest.raises(ProviderError) as excinfo:
        google_oauth.exchange_code("a-code", "http://localhost:8000/api/auth/google/callback")
    assert "HTTP 503" in str(excinfo.value)


def test_callback_reports_the_exchange_reason_to_the_frontend(client, monkeypatch):
    """A token-exchange failure reaches /login with the actionable reason attached."""
    from urllib.parse import parse_qs, urlparse

    from app.api.routes import auth as auth_routes
    from app.core.exceptions import ProviderError

    reason = (
        "Google rejected this server's OAuth credentials (invalid_client). "
        "Check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then restart the backend."
    )

    def boom(code, redirect_uri):
        assert redirect_uri.endswith("/api/auth/google/callback")
        raise ProviderError(reason)

    monkeypatch.setattr(auth_routes, "exchange_code", boom)
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "abc", "state": make_state("testclient")},
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["oauth_error"] == ["OAUTH_TOKEN_EXCHANGE"]
    assert query["message"] == [reason]  # exact reason, not a generic sentence


def test_callback_reports_a_disabled_account_distinctly(client, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from app.api.routes import auth as auth_routes
    from app.core.exceptions import PermissionDeniedError

    monkeypatch.setattr(auth_routes, "exchange_code", lambda code, uri: {"email": "x@y.z", "sub": "1"})
    monkeypatch.setattr(
        auth_routes,
        "get_or_create_google_user",
        lambda claims, db: (_ for _ in ()).throw(PermissionDeniedError("Account is disabled.")),
    )
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "abc", "state": make_state("testclient")},
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["oauth_error"] == ["OAUTH_ACCOUNT_DISABLED"]
    assert query["message"] == ["Account is disabled."]


def test_callback_does_not_echo_an_unrecognised_error_param(client):
    """`error` is attacker-controllable query text and must not be reflected."""
    hostile = "<script>alert(1)</script>"
    response = client.get(
        "/api/auth/google/callback",
        params={"error": hostile, "state": make_state("testclient")},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "oauth_error=OAUTH_CANCELLED" in location
    assert "alert" not in location
    assert "%3Cscript" not in location.lower()
