from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base

_engine = None
_session_factory: sessionmaker | None = None


def get_engine():
    """Create (once) the SQLAlchemy engine from current settings."""
    global _engine
    if _engine is not None:
        return _engine
    settings = get_settings()
    connect_args: dict = {}
    if settings.is_sqlite:
        connect_args = {"check_same_thread": False, "timeout": 30}
        url = settings.database_url
        if url in ("sqlite://", "sqlite:///:memory:"):
            _engine = create_engine("sqlite://", connect_args=connect_args, poolclass=StaticPool)
        else:
            _engine = create_engine(url, connect_args=connect_args)

            def _sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
                # WAL lets the API's readers coexist with the worker's writer,
                # avoiding read/write starvation during progress polling.
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

            event.listen(_engine, "connect", _sqlite_pragmas)
    else:
        _engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
    return _engine


def reset_engine() -> None:
    """Used by tests to rebuild the engine against an isolated database."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)
    return _session_factory


def create_all() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def drop_all() -> None:
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=get_engine())


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context-manager style session for services/workers."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
