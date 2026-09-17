from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.inference.registry import create_provider, get_definition, load_model_definitions, resolve_env_refs
from app.models import ModelInfo

# Fields that may be mirrored into the database (never secrets / api keys).
_SAFE_FIELDS = {
    "display_name", "provider", "model_id", "description", "device", "torch_dtype",
    "api_style", "supports_logprobs", "timeout_seconds", "max_retries",
    "memorization_ratio", "memorization_delta", "model_version",
    "trust_remote_code", "load_in_8bit", "endpoint",
}


def seed_models_from_config(db: Session) -> int:
    """Insert/refresh registry rows from configs/models.yaml. Returns count."""
    created = 0
    for name, definition in load_model_definitions().items():
        row = db.execute(select(ModelInfo).where(ModelInfo.name == name)).scalar_one_or_none()
        safe = {k: v for k, v in definition.items() if k in _SAFE_FIELDS and v is not None}
        if row is None:
            db.add(
                ModelInfo(
                    name=name,
                    display_name=definition.get("display_name") or name,
                    provider=definition.get("provider") or "unknown",
                    model_id=definition.get("model_id") or name,
                    description=definition.get("description") or "",
                    config_json=json.dumps(safe, ensure_ascii=True),
                )
            )
            created += 1
        else:
            row.display_name = definition.get("display_name") or row.display_name
            row.provider = definition.get("provider") or row.provider
            row.model_id = definition.get("model_id") or row.model_id
            row.description = definition.get("description") or row.description
            row.config_json = json.dumps(safe, ensure_ascii=True)
            row.is_active = True
    return created


def list_models(db: Session) -> list[ModelInfo]:
    return list(db.execute(select(ModelInfo).order_by(ModelInfo.display_name)).scalars().all())


def get_model(db: Session, model_id: int) -> ModelInfo:
    row = db.get(ModelInfo, model_id)
    if row is None:
        raise NotFoundError(f"Model {model_id} does not exist.")
    return row


def resolve_definition(row: ModelInfo) -> dict:
    """Build a provider definition for a DB model row.

    Prefers the entry in configs/models.yaml; falls back to synthesizing a
    definition from the row (env references in config_json are resolved at
    use time, so secrets never live in the database).
    """
    try:
        return get_definition(row.name)
    except Exception:
        pass
    config = {}
    try:
        config = json.loads(row.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    config = resolve_env_refs(config)
    return {
        "name": row.name,
        "display_name": row.display_name or row.name,
        "provider": row.provider,
        "model_id": row.model_id or row.name,
        "description": row.description,
        **config,
    }


def build_provider(row: ModelInfo):
    definition = resolve_definition(row)
    return create_provider(row.name, definition)


def register_model(db: Session, *, name: str, display_name: str, provider: str, model_id: str,
                   description: str, config_json: str) -> ModelInfo:
    existing = db.execute(select(ModelInfo).where(ModelInfo.name == name)).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(f"A model named '{name}' already exists.", code="CONFLICT")
    # Validate configuration parses and secrets are referenced, never stored inline.
    try:
        config = json.loads(config_json or "{}")
    except json.JSONDecodeError:
        raise ValidationError("config_json must be valid JSON.")
    forbidden_secret_patterns = ("api_key", "token", "secret", "password", "authorization")
    if any(any(pat in str(k).lower() for pat in forbidden_secret_patterns) and "api_key_env" not in str(k) for k in config):
        raise ValidationError(
            "Secrets must not be stored in the database. Reference environment "
            "variables instead, e.g. \"api_key\": \"${MY_API_KEY}\"."
        )
    row = ModelInfo(
        name=name,
        display_name=display_name or name,
        provider=provider,
        model_id=model_id or name,
        description=description,
        config_json=json.dumps(config, ensure_ascii=True),
    )
    db.add(row)
    db.flush()
    return row
