from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models import DatasetItem, Experiment, User
from app.models.enums import ExperimentStage, ExperimentStatus
from app.schemas.experiment import ExperimentCreate, ThresholdConfig
from app.services.dataset_service import get_dataset
from app.services.model_service import get_model


def _defaults() -> dict:
    settings = get_settings()
    return {
        "mutation_count": settings.default_mutation_count,
        "mutation_seed": settings.default_mutation_seed,
        "mutation_strength": settings.default_mutation_strength,
        "batch_size": settings.default_batch_size,
        "max_tokens": settings.default_max_tokens,
        "temperature": settings.default_temperature,
        "device": settings.device,
    }


def create_experiment(db: Session, user: User, payload: ExperimentCreate) -> Experiment:
    defaults = _defaults()
    dataset = get_dataset(db, payload.dataset_id)
    model_row = get_model(db, payload.model_id)
    if not model_row.is_active:
        raise ValidationError("The selected model is inactive.", code="MODEL_UNAVAILABLE")
    if model_row.provider == "mock":
        pass  # mock provider always available

    if dataset.item_count == 0:
        raise ValidationError("The dataset contains no items.", code="EMPTY_DATASET")

    if payload.mutation_strategy not in ("identifier_rename",):
        raise ValidationError(
            f"Unsupported mutation strategy '{payload.mutation_strategy}'. "
            "Supported: identifier_rename.",
            code="UNSUPPORTED_MUTATION_STRATEGY",
        )
    # Identifier renaming is implemented for Python.
    languages = db.execute(
        select(func.count()).select_from(DatasetItem).where(
            DatasetItem.dataset_id == dataset.id, DatasetItem.language != "python"
        )
    ).scalar_one()
    if int(languages) > 0:
        raise ValidationError(
            "The dataset contains non-Python items; the identifier_rename mutation "
            "strategy currently supports Python only.",
            code="UNSUPPORTED_LANGUAGE",
        )

    thresholds = ThresholdConfig() if payload.thresholds is None else payload.thresholds
    settings = get_settings()
    config = {
        "thresholds": thresholds.model_dump(),
        "token_losses_enabled": payload.token_losses_enabled
        if payload.token_losses_enabled is not None
        else bool(settings.enable_token_loss_storage),
        "cache_enabled": payload.cache_enabled
        if payload.cache_enabled is not None
        else bool(settings.enable_inference_cache),
    }

    model_version = (model_row.model_id or model_row.name) + "@configured"
    experiment = Experiment(
        name=payload.name,
        description=payload.description or "",
        created_by=user.id,
        model_id=model_row.id,
        dataset_id=dataset.id,
        dataset_hash=dataset.content_hash,
        model_version=model_version,
        mutation_count=payload.mutation_count if payload.mutation_count is not None else defaults["mutation_count"],
        mutation_seed=payload.mutation_seed if payload.mutation_seed is not None else defaults["mutation_seed"],
        mutation_strength=payload.mutation_strength
        if payload.mutation_strength is not None
        else defaults["mutation_strength"],
        mutation_strategy=payload.mutation_strategy,
        temperature=payload.temperature if payload.temperature is not None else defaults["temperature"],
        max_tokens=payload.max_tokens if payload.max_tokens is not None else defaults["max_tokens"],
        batch_size=payload.batch_size if payload.batch_size is not None else defaults["batch_size"],
        device=payload.device or defaults["device"],
        config_json=json.dumps(config),
        status=ExperimentStatus.QUEUED.value,
        current_stage=ExperimentStage.QUEUED.value,
        total_items=dataset.item_count,
        processed_items=0,
    )
    db.add(experiment)
    db.flush()
    return experiment


def get_experiment(db: Session, experiment_id: int) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise NotFoundError(f"Experiment {experiment_id} does not exist.")
    return experiment


def list_experiments(db: Session, *, offset: int = 0, limit: int = 50) -> tuple[list[Experiment], int]:
    total = db.execute(select(func.count()).select_from(Experiment)).scalar_one()
    rows = db.execute(
        select(Experiment).order_by(Experiment.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return list(rows), int(total)


def cancel_experiment(db: Session, experiment_id: int) -> Experiment:
    experiment = get_experiment(db, experiment_id)
    if experiment.status in (ExperimentStatus.COMPLETED.value, ExperimentStatus.CANCELLED.value):
        raise ValidationError(
            f"Cannot cancel an experiment in state {experiment.status}.",
            code="INVALID_STATE",
        )
    if experiment.status == ExperimentStatus.FAILED.value:
        return experiment
    experiment.status = ExperimentStatus.CANCELLED.value
    experiment.progress_message = "Cancellation requested."
    if experiment.completed_at is None:
        experiment.completed_at = datetime.now(timezone.utc)
    return experiment


def mark_failed(db: Session, experiment_id: int, *, error_code: str, error_message: str) -> None:
    experiment = get_experiment(db, experiment_id)
    experiment.status = ExperimentStatus.FAILED.value
    experiment.error_code = error_code
    experiment.error_message = error_message[:4000]
    experiment.current_stage = "failed"
    experiment.completed_at = datetime.now(timezone.utc)
    experiment.progress_message = f"Experiment failed: {error_code}"
