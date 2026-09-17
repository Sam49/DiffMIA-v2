from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import metrics as M
from app.analysis.conclusion import build_conclusion
from app.analysis.distributions import histogram, kde
from app.models import AnalysisResult, DatasetItem, Experiment, ModelInfo, User
from app.services.dataset_service import get_dataset
from app.services.experiment_service import get_experiment


def _float_or_none(value) -> float | None:
    return None if value is None else float(value)


def build_results(db: Session, experiment_id: int) -> dict:
    """Deterministic bundle describing an experiment's full results."""
    experiment = get_experiment(db, experiment_id)
    dataset = get_dataset(db, experiment.dataset_id)
    model = db.get(ModelInfo, experiment.model_id)
    creator = db.get(User, experiment.created_by)

    rows = db.execute(
        select(AnalysisResult, DatasetItem)
        .join(DatasetItem, AnalysisResult.snippet_id == DatasetItem.id)
        .where(AnalysisResult.experiment_id == experiment_id)
        .order_by(DatasetItem.position)
    ).all()

    analyses = []
    ci_values: list[float] = []
    z_values: list[float] = []
    original_losses: list[float] = []
    mutation_losses: list[float] = []
    pairs: list[list[float]] = []

    for analysis, snippet in rows:
        ci = _float_or_none(analysis.contamination_index)
        if ci is not None:
            ci_values.append(ci)
        if analysis.z_score is not None:
            z_values.append(float(analysis.z_score))
        if analysis.original_loss is not None:
            original_losses.append(float(analysis.original_loss))
        if analysis.mean_mutation_loss is not None:
            mutation_losses.append(float(analysis.mean_mutation_loss))
        if analysis.original_loss is not None and analysis.mean_mutation_loss is not None:
            pairs.append([float(analysis.original_loss), float(analysis.mean_mutation_loss)])
        analyses.append(
            {
                "snippet_id": snippet.id,
                "external_id": snippet.external_id,
                "dataset_name": snippet.dataset_name,
                "problem_statement": snippet.problem_statement,
                "code": snippet.code,
                "language": snippet.language,
                "metadata_json": snippet.metadata_json,
                "original_loss": _float_or_none(analysis.original_loss),
                "original_token_count": analysis.original_token_count,
                "mean_mutation_loss": _float_or_none(analysis.mean_mutation_loss),
                "median_mutation_loss": _float_or_none(analysis.median_mutation_loss),
                "std_mutation_loss": _float_or_none(analysis.std_mutation_loss),
                "mutation_count_used": analysis.mutation_count_used,
                "mutation_count_requested": analysis.mutation_count_requested,
                "contamination_index": ci,
                "abs_loss_delta": _float_or_none(analysis.abs_loss_delta),
                "rel_loss_delta": _float_or_none(analysis.rel_loss_delta),
                "z_score": _float_or_none(analysis.z_score),
                "z_score_global": _float_or_none(analysis.z_score_global),
                "effect_size": _float_or_none(analysis.effect_size),
                "percentile_rank": _float_or_none(analysis.percentile_rank),
                "classification": analysis.classification,
                "classification_reason": analysis.classification_reason,
                "flagged": analysis.flagged,
                "extra_json": analysis.extra_json,
            }
        )

    flagged = sum(1 for a in analyses if a["flagged"])
    high_signal = sum(1 for a in analyses if a["classification"] == "HIGH_CONTAMINATION_SIGNAL")
    low_evidence = sum(1 for a in analyses if a["classification"] == "LOW_EVIDENCE")
    classifications: dict[str, int] = {}
    for a in analyses:
        classifications[a["classification"]] = classifications.get(a["classification"], 0) + 1

    def dist(values: list[float], label: str) -> dict:
        centers, counts = histogram(values, bins=30)
        kx, ky = kde(values)
        return {"label": label, "values": values, "histogram_x": centers,
                "histogram_y": counts, "kde_x": kx, "kde_y": ky}

    distributions = {
        "ci": dist(ci_values, "Contamination Index"),
        "z": dist(z_values, "Dataset Z-score"),
        "original_loss": dist(original_losses, "Original loss"),
        "mutation_loss": dist(mutation_losses, "Mean mutated loss"),
    }

    stats = {
        "analyzed_count": len(analyses),
        "flagged_count": flagged,
        "high_signal_count": high_signal,
        "low_evidence_count": low_evidence,
        "failed_snippets": max(experiment.total_items - len(analyses), 0),
        "mean_ci": M.mean(ci_values) if ci_values else None,
        "median_ci": M.median(ci_values),
        "std_ci": M.std(ci_values, ddof=1),
        "mean_z": M.mean(z_values) if z_values else None,
        "mean_original_loss": M.mean(original_losses) if original_losses else None,
        "mean_mutation_loss": M.mean(mutation_losses) if mutation_losses else None,
        "total_items": experiment.total_items,
        "epsilon": 1e-9,
    }

    bundle = {
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "description": experiment.description,
            "created_by": experiment.created_by,
            "model_id": experiment.model_id,
            "dataset_id": experiment.dataset_id,
            "dataset_hash": experiment.dataset_hash,
            "model_version": experiment.model_version,
            "mutation_count": experiment.mutation_count,
            "mutation_seed": experiment.mutation_seed,
            "mutation_strength": experiment.mutation_strength,
            "mutation_strategy": experiment.mutation_strategy,
            "temperature": experiment.temperature,
            "max_tokens": experiment.max_tokens,
            "batch_size": experiment.batch_size,
            "device": experiment.device,
            "config_json": experiment.config_json,
            "status": experiment.status,
            "current_stage": experiment.current_stage,
            "progress_message": experiment.progress_message,
            "total_items": experiment.total_items,
            "processed_items": experiment.processed_items,
            "error_code": experiment.error_code,
            "error_message": experiment.error_message,
            "created_at": experiment.created_at,
            "started_at": experiment.started_at,
            "completed_at": experiment.completed_at,
            "model": {
                "id": model.id,
                "name": model.name,
                "display_name": model.display_name,
                "provider": model.provider,
                "model_id": model.model_id,
                "description": model.description,
                "config_json": model.config_json,
                "is_active": model.is_active,
            } if model else None,
            "dataset": {
                "id": dataset.id,
                "name": dataset.name,
                "description": dataset.description,
                "source_format": dataset.source_format,
                "content_hash": dataset.content_hash,
                "item_count": dataset.item_count,
            },
            "created_by_user": creator.username if creator else "",
        },
        "stats": stats,
        "analyses": analyses,
        "classifications": classifications,
        "distributions": distributions,
        "pairs": pairs,
    }
    # The verdict is derived from the numbers above, so it is computed last and
    # travels with every consumer of the bundle (API, JSON/Markdown/PDF reports).
    bundle["conclusion"] = build_conclusion(bundle)
    return bundle
