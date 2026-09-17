"""Persistent inference-result cache.

Cache key is a SHA-256 over (model key, model version, input text,
inference configuration), so rerunning an identical experiment reuses cached
inference results when safe. The cache lives in a database table (works with
SQLite and PostgreSQL) and is shared across experiments.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InferenceCache

CACHE_SCHEMA_VERSION = "v1"


def compute_cache_key(model_key: str, model_version: str, text: str, config: dict | None = None) -> str:
    payload = {
        "v": CACHE_SCHEMA_VERSION,
        "model": model_key,
        "version": model_version,
        "text": text,
        "config": config or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cached(db: Session, cache_key: str) -> str | None:
    row = db.execute(select(InferenceCache).where(InferenceCache.cache_key == cache_key)).scalar_one_or_none()
    return row.payload_json if row else None


def put_cached(db: Session, cache_key: str, model_key: str, input_hash: str, payload: dict) -> None:
    """Store a result, tolerating an existing row with the same key.

    The write is an atomic upsert on the key: a plain select-then-insert breaks
    when the same input is scored twice before a flush (sessions here use
    ``autoflush=False``) or when two workers score the same text concurrently —
    both surfaced as ``UNIQUE constraint failed: inference_cache.cache_key`` and
    aborted the whole experiment.
    """
    values = {
        "cache_key": cache_key,
        "model_key": model_key,
        "input_hash": input_hash,
        "payload_json": json.dumps(payload),
    }
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = sqlite_insert(InferenceCache).values(**values)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[InferenceCache.cache_key],
                set_={"payload_json": statement.excluded.payload_json},
            )
        )
        return
    if dialect in ("postgresql", "postgres"):
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        statement = pg_insert(InferenceCache).values(**values)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[InferenceCache.cache_key],
                set_={"payload_json": statement.excluded.payload_json},
            )
        )
        return

    # Unknown dialect: keep the portable path, but look at pending rows too so a
    # second write for the same key within one transaction cannot duplicate.
    existing = db.execute(select(InferenceCache).where(InferenceCache.cache_key == cache_key)).scalar_one_or_none()
    if existing is None:
        existing = next(
            (
                obj
                for obj in db.new
                if isinstance(obj, InferenceCache) and obj.cache_key == cache_key
            ),
            None,
        )
    if existing is None:
        db.add(InferenceCache(**values))
    else:
        existing.payload_json = values["payload_json"]


def input_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dedupe_by_cache_key(keys: list[str]) -> tuple[list[int], dict[int, list[int]]]:
    """Group a batch of cache keys by identity.

    Returns ``(unique positions, representative position -> all positions)``.
    Scoring identical text twice yields the same number, so the provider is
    called once per distinct input while every request still gets persisted.
    """
    unique: list[int] = []
    groups: dict[int, list[int]] = {}
    seen: dict[str, int] = {}
    for position, key in enumerate(keys):
        if key in seen:
            groups[seen[key]].append(position)
            continue
        seen[key] = position
        unique.append(position)
        groups[position] = [position]
    return unique, groups
