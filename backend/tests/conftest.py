"""Test configuration.

Environment is configured *before* any application module is imported so the
cached Settings and lazy database engine point at an isolated SQLite file.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

_TEST_DIR = tempfile.mkdtemp(prefix="diffmia_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TEST_DIR, 'test.db').replace(os.sep, '/')}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "1000000"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin"
# Hermetic auth defaults — a developer's .env must not change test outcomes.
os.environ["REGISTRATION_ENABLED"] = "false"
os.environ["REGISTRATION_DEFAULT_ROLE"] = "VIEWER"
os.environ["EMAIL_VERIFICATION_REQUIRED"] = "false"
os.environ["AUTO_LOGIN_ENABLED"] = "false"
os.environ["ENABLE_INFERENCE_CACHE"] = "true"
# Blank (not merely absent) so a real OAuth client in .env cannot leak in and flip
# google_enabled. Tests that need it enabled patch the settings object instead.
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
# Left empty so tests exercise the derived redirect URI, not a pinned deployment value.
os.environ["OAUTH_REDIRECT_URI"] = ""


@pytest.fixture(autouse=True)
def clean_database():
    """Fresh schema + seed defaults for every test."""
    from app.db.session import create_all, drop_all
    from app.scripts.seed import seed_defaults

    drop_all()
    create_all()
    seed_defaults()
    yield


def _make_token(user_id: int, username: str, role: str) -> str:
    from app.core.config import get_settings
    from app.core.security import create_access_token

    settings = get_settings()
    return create_access_token(
        {"sub": str(user_id), "username": username, "role": role},
        settings.secret_key,
        60,
    )


@pytest.fixture()
def admin_headers():
    """Bearer headers for the seeded admin user."""
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models import User

    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.username == "admin")).scalar_one()
        token = _make_token(user.id, user.username, user.role)
    finally:
        session.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def make_user_token():
    """Factory: token for a created user."""

    def _make(username: str, role: str) -> dict:
        from sqlalchemy import select

        from app.db.session import get_session_factory
        from app.models import User

        session = get_session_factory()()
        try:
            user = session.execute(select(User).where(User.username == username)).scalar_one()
            token = _make_token(user.id, user.username, user.role)
        finally:
            session.close()
        return {"Authorization": f"Bearer {token}"}

    return _make


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
