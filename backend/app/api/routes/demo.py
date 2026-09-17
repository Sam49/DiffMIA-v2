"""One-click DEMO MODE.

POST /api/demo/run  → bootstrap sample dataset + mock model, then create and
                      launch a complete experiment. No GPU / token / API needed.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.session import get_db
from app.inference.registry import load_model_definitions
from app.models import Dataset, ModelInfo, User
from app.models.enums import UserRole
from app.schemas.experiment import ExperimentCreate
from app.services import dataset_service, experiment_service
from app.workers.executor import executor

logger = logging.getLogger("diffmia.demo")
router = APIRouter(tags=["demo"])


def _ensure_demo_assets(db: Session) -> dict:
    settings = get_settings()
    mock_name = settings.demo_model_id

    model_row = db.execute(select(ModelInfo).where(ModelInfo.name == mock_name)).scalar_one_or_none()
    if model_row is None:
        definition = (load_model_definitions() or {}).get(mock_name)
        if definition is None:
            raise ValidationError(
                f"Mock model '{mock_name}' is not declared in configs/models.yaml.",
                code="MODEL_CONFIGURATION",
            )
        from app.services.model_service import register_model

        model_row = register_model(
            db,
            name=mock_name,
            display_name=definition.get("display_name", "DiffMIA Mock (Demo)"),
            provider="mock",
            model_id=definition.get("model_id", mock_name),
            description=definition.get("description", "Deterministic demo provider."),
            config_json="{}",
        )
    db.flush()

    dataset_path = Path(settings.demo_dataset_path)
    if not dataset_path.exists():
        raise ValidationError(
            f"Sample dataset file not found at {dataset_path}.", code="DEMO_DATASET_MISSING"
        )
    content = dataset_path.read_text(encoding="utf-8")
    # Reuse an existing dataset with the same fingerprint when possible.
    existing = None
    if content:
        from app.services.dataset_parsers import parse_dataset_content

        try:
            records, _ = parse_dataset_content(content, source_format="jsonl",
                                               default_dataset="DiffMIA Sample")
            existing = db.execute(
                select(Dataset).where(Dataset.content_hash == dataset_service.records_hash(records))
            ).scalar_one_or_none()
            dataset = existing
            if dataset is None:
                dataset, _ = dataset_service.create_dataset(
                    db, name="DiffMIA Sample", records=records,
                    description="Sample Python benchmark snippets for demo mode.",
                    source_format="jsonl",
                )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Sample dataset is malformed: {exc}", code="DEMO_DATASET_MISSING") from exc
    else:
        raise ValidationError("Sample dataset is empty.", code="DEMO_DATASET_MISSING")
    db.flush()
    return {"dataset_id": dataset.id, "model_id": model_row.id}


@router.get("/demo/status")
def demo_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    model_ready = db.execute(
        select(ModelInfo).where(ModelInfo.name == settings.demo_model_id, ModelInfo.provider == "mock")
    ).scalar_one_or_none() is not None
    dataset_ready = Path(settings.demo_dataset_path).exists()
    return {
        "mode": "DEMO",
        "model_ready": model_ready,
        "dataset_ready": dataset_ready,
        "mock_model": settings.demo_model_id,
        "hint": "DEMO MODE: uses deterministic synthetic losses — no GPU, token or API required.",
    }


@router.post("/demo/bootstrap")
def demo_bootstrap(
    user: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> dict:
    assets = _ensure_demo_assets(db)
    return {"status": "ok", **assets}


@router.post("/demo/run")
def demo_run(
    name: str = "Demo experiment",
    user: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> dict:
    assets = _ensure_demo_assets(db)
    payload = ExperimentCreate(
        name=name,
        description="One-click DEMO MODE experiment with deterministic synthetic losses.",
        dataset_id=assets["dataset_id"],
        model_id=assets["model_id"],
    )
    experiment = experiment_service.create_experiment(db, user, payload)
    executor.dispatch(experiment.id)
    logger.info("Demo experiment %s queued", experiment.id)
    return {"status": "queued", "experiment_id": experiment.id, **assets}
