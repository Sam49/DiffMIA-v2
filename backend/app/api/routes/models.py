from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.exceptions import NotFoundError, ProviderError
from app.db.session import get_db
from app.inference import device as device_util
from app.inference.registry import manager as provider_manager
from app.models import ModelInfo, User
from app.models.enums import UserRole
from app.schemas.common import MessageOut
from app.schemas.model import ModelCreate, ModelOut, ModelStatusOut
from app.services import model_service

router = APIRouter(tags=["models"])


def _out(row: ModelInfo) -> ModelOut:
    return ModelOut(
        id=row.id, name=row.name, display_name=row.display_name, provider=row.provider,
        model_id=row.model_id, description=row.description, config_json=row.config_json,
        is_active=row.is_active,
    )


@router.get("/models")
def list_models(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows = model_service.list_models(db)
    items = []
    for row in rows:
        data = _out(row).model_dump(mode="json")
        try:
            capabilities = provider_manager.status(row.name)
            data["is_mock"] = capabilities.get("is_mock", False)
            data["supports_logprobs"] = capabilities.get("supports_logprobs", False)
        except ProviderError:
            data["is_mock"] = row.provider == "mock"
            data["supports_logprobs"] = row.provider == "mock" or row.provider == "transformers"
        items.append(data)
    return {"items": items, "total": len(items)}


@router.get("/models/{model_id}/status", response_model=ModelStatusOut)
def model_status(
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ModelStatusOut:
    row = model_service.get_model(db, model_id)
    try:
        definition = model_service.resolve_definition(row)
        from app.inference.registry import provider_capabilities

        caps = provider_capabilities(row.name)
    except ProviderError as exc:
        caps = {"is_mock": row.provider == "mock", "supports_logprobs": False}
        status = provider_manager.status(row.name)
        status["load_error"] = exc.message
        return ModelStatusOut(
            id=row.id, name=row.name, display_name=row.display_name, provider=row.provider,
            supports_logprobs=caps["supports_logprobs"], is_mock=caps["is_mock"], load_error=exc.message,
        )
    status = provider_manager.status(row.name)
    return ModelStatusOut(
        id=row.id, name=row.name, display_name=row.display_name, provider=row.provider,
        supports_logprobs=caps["supports_logprobs"], is_mock=caps["is_mock"],
        loaded=status.get("loaded", False), device=row.device if row.provider == "transformers" else "",
        load_error=status.get("load_error", ""), health="ok" if status.get("loaded") else "not_loaded",
    )


@router.get("/models/status")
def all_models_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    device = device_util.detect_device()
    return {
        "device": device,
        "gpu": device_util.gpu_status(),
        "loaded": provider_manager.loaded_names(),
    }


@router.post("/models", response_model=ModelOut, status_code=201)
def register_model(
    payload: ModelCreate,
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> ModelOut:
    row = model_service.register_model(
        db, name=payload.name, display_name=payload.display_name, provider=payload.provider,
        model_id=payload.model_id, description=payload.description, config_json=payload.config_json,
    )
    return _out(row)


@router.post("/models/{model_id}/load", response_model=ModelStatusOut)
def load_model(
    model_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> ModelStatusOut:
    row = model_service.get_model(db, model_id)
    definition = model_service.resolve_definition(row)
    try:
        provider_manager.load(row.name, definition)
        loaded = True
        error = ""
    except ProviderError as exc:
        loaded = False
        error = exc.message
    caps = {"is_mock": row.provider == "mock", "supports_logprobs": True}
    return ModelStatusOut(
        id=row.id, name=row.name, display_name=row.display_name, provider=row.provider,
        supports_logprobs=caps["supports_logprobs"], is_mock=caps["is_mock"],
        loaded=loaded, load_error=error, health="ok" if loaded else "error",
    )


@router.post("/models/{model_id}/unload", response_model=MessageOut)
def unload_model(
    model_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> MessageOut:
    row = model_service.get_model(db, model_id)
    provider_manager.unload(row.name)
    return MessageOut(message=f"Model '{row.name}' unloaded.")
