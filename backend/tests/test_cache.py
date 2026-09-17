from __future__ import annotations

from app.db.session import get_session_factory
from app.services import cache_service


def test_cache_key_deterministic_and_sensitive():
    k1 = cache_service.compute_cache_key("m", "v1", "code", {"temperature": 0.0})
    k2 = cache_service.compute_cache_key("m", "v1", "code", {"temperature": 0.0})
    assert k1 == k2
    k3 = cache_service.compute_cache_key("m", "v1", "code", {"temperature": 0.5})
    assert k1 != k3
    k4 = cache_service.compute_cache_key("other", "v1", "code", {"temperature": 0.0})
    assert k1 != k4
    k5 = cache_service.compute_cache_key("m", "v1", "code ", {"temperature": 0.0})
    assert k1 != k5


def test_cache_roundtrip():
    session = get_session_factory()()
    try:
        key = cache_service.compute_cache_key("mock", "1.0", "def f():\n    pass", {"a": 1})
        assert cache_service.get_cached(session, key) is None
        cache_service.put_cached(session, key, "mock", "inphash", {"mean_loss": 0.5})
        session.commit()
        payload = cache_service.get_cached(session, key)
        assert payload is not None
        assert '"mean_loss": 0.5' in payload
    finally:
        session.rollback()
        session.close()
