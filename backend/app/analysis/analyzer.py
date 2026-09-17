"""Analyzer: turns per-snippet inference runs into AnalysisResult rows.

Runs a differential analysis over one experiment:

1. group inference runs by snippet,
2. compute original loss and per-mutation losses,
3. compute CI / deltas / effect size per snippet,
4. compute a dataset baseline (mean/median/std CI) and per-snippet Z-scores
   and percentile ranks (dataset-normalized),
5. compute a *global* Z-score against all experiments for the same model,
6. classify every snippet and persist the rows.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis import metrics as M
from app.analysis.classifier import ClassificationThresholds, classify_snippet
from app.models import (
    AnalysisResult,
    DatasetItem,
    Experiment,
    ExperimentLog,
    InferenceRun,
)
from app.models.enums import InferenceStatus, Variant

logger = logging.getLogger("diffmia.analysis")


@dataclass
class _ItemStats:
    snippet_id: int
    original_loss: float | None = None
    original_token_count: int | None = None
    mutation_losses: list[float] = field(default_factory=list)
    mutation_count_used: int = 0
    ci: float | None = None
    abs_delta: float | None = None
    rel_delta: float | None = None
    effect: float | None = None
    median_mutation: float | None = None
    std_mutation: float | None = None
    analyzed: bool = False


def _runs_grouped(db: Session, experiment_id: int) -> dict[int, list[InferenceRun]]:
    rows = db.execute(
        select(InferenceRun)
        .where(InferenceRun.experiment_id == experiment_id)
        .order_by(InferenceRun.created_at)
    ).scalars()
    grouped: dict[int, list[InferenceRun]] = {}
    for run in rows:
        grouped.setdefault(run.snippet_id, []).append(run)
    return grouped


def analyze_experiment(
    db: Session,
    experiment: Experiment,
    thresholds: ClassificationThresholds | None = None,
) -> dict:
    thresholds = thresholds or _thresholds_for(experiment)

    items = db.execute(
        select(DatasetItem)
        .where(DatasetItem.dataset_id == experiment.dataset_id)
        .order_by(DatasetItem.position)
    ).scalars().all()
    runs = _runs_grouped(db, experiment.id)

    stats_by_snippet: dict[int, _ItemStats] = {}
    for item in items:
        stats = _ItemStats(snippet_id=item.id)
        item_runs = runs.get(item.id, [])
        original = next(
            (r for r in item_runs if r.variant == Variant.ORIGINAL.value and r.status == InferenceStatus.SUCCESS.value), None
        )
        if original is not None and original.mean_loss is not None:
            stats.original_loss = original.mean_loss
            stats.original_token_count = original.token_count

        by_index: dict[int, float] = {}
        for run in item_runs:
            if run.variant != Variant.MUTATION.value or run.status != InferenceStatus.SUCCESS.value:
                continue
            if run.mean_loss is None or run.mutation_index is None:
                continue
            by_index[run.mutation_index] = run.mean_loss
        stats.mutation_losses = [by_index[k] for k in sorted(by_index)]
        stats.mutation_count_used = len(stats.mutation_losses)
        stats.median_mutation = M.median(stats.mutation_losses)
        stats.std_mutation = M.std(stats.mutation_losses, ddof=1)

        if stats.original_loss is not None and stats.mutation_losses:
            stats.ci = M.contamination_index(stats.original_loss, stats.mutation_losses)
            stats.abs_delta = M.absolute_delta(stats.original_loss, stats.mutation_losses)
            stats.rel_delta = M.relative_delta(stats.original_loss, stats.mutation_losses)
            stats.effect = M.effect_size(stats.original_loss, stats.mutation_losses)
            stats.analyzed = True
        stats_by_snippet[item.id] = stats

    # Dataset baseline (normalized z + percentile rank)
    valid_cis = [s.ci for s in stats_by_snippet.values() if s.ci is not None]
    baseline_available = len(valid_cis) >= thresholds.min_items_for_baseline

    # Global population: same model across other experiments
    other = db.execute(
        select(AnalysisResult.contamination_index)
        .join(Experiment, AnalysisResult.experiment_id == Experiment.id)
        .where(Experiment.model_id == experiment.model_id, Experiment.id != experiment.id)
        .where(AnalysisResult.contamination_index.is_not(None))
    ).scalars().all()
    global_cis: list[float] = list(valid_cis)
    global_cis.extend(float(x) for x in other if x is not None)

    # Delete stale rows for this experiment (deterministic re-analysis)
    db.execute(delete(AnalysisResult).where(AnalysisResult.experiment_id == experiment.id))

    summary: dict = {
        "analyzed_count": 0,
        "flagged_count": 0,
        "high_signal_count": 0,
        "low_evidence_count": 0,
        "classifications": {},
        "mean_ci": None,
        "median_ci": None,
        "std_ci": None,
    }

    for item in items:
        stats = stats_by_snippet[item.id]
        z = M.leave_one_out_z_score(stats.ci, valid_cis) if stats.ci is not None and baseline_available else None
        z_global = M.leave_one_out_z_score(stats.ci, global_cis) if stats.ci is not None and len(global_cis) >= 3 else None
        percentile = M.percentile_rank(stats.ci, valid_cis) if stats.ci is not None else None

        decision = classify_snippet(
            contamination_index=stats.ci,
            z_score=z,
            mutation_count_used=stats.mutation_count_used,
            mutation_count_requested=experiment.mutation_count,
            thresholds=thresholds,
            baseline_available=baseline_available,
            original_available=stats.original_loss is not None,
        )

        row = AnalysisResult(
            experiment_id=experiment.id,
            snippet_id=item.id,
            original_loss=stats.original_loss,
            original_token_count=stats.original_token_count,
            mean_mutation_loss=M.mean(stats.mutation_losses) if stats.mutation_losses else None,
            median_mutation_loss=stats.median_mutation,
            std_mutation_loss=stats.std_mutation,
            mutation_count_used=stats.mutation_count_used,
            mutation_count_requested=experiment.mutation_count,
            contamination_index=stats.ci,
            abs_loss_delta=stats.abs_delta,
            rel_loss_delta=stats.rel_delta,
            z_score=z,
            z_score_global=z_global,
            effect_size=stats.effect,
            percentile_rank=percentile,
            classification=decision.classification.value,
            classification_reason=decision.reason,
            flagged=decision.flagged,
            extra_json=json.dumps({"baseline_items": len(valid_cis)}),
        )
        db.add(row)
        if stats.analyzed:
            summary["analyzed_count"] += 1
        summary["classifications"][decision.classification.value] = summary["classifications"].get(
            decision.classification.value, 0
        ) + 1
        if decision.flagged:
            summary["flagged_count"] += 1
        if decision.classification.value == "HIGH_CONTAMINATION_SIGNAL":
            summary["high_signal_count"] += 1
        if decision.classification.value == "LOW_EVIDENCE":
            summary["low_evidence_count"] += 1

    if valid_cis:
        summary["mean_ci"] = M.mean(valid_cis)
        summary["median_ci"] = M.median(valid_cis)
        summary["std_ci"] = M.std(valid_cis, ddof=1)
    summary["total_items"] = len(items)
    summary["failed_snippets"] = len(items) - summary["analyzed_count"]
    summary["baseline_available"] = baseline_available

    db.add(
        ExperimentLog(
            experiment_id=experiment.id,
            level="INFO",
            message=f"Analysis complete: {summary['analyzed_count']} snippets analyzed, "
            f"{summary['flagged_count']} flagged.",
            context_json=json.dumps({"summary": summary}),
        )
    )
    return summary


def _thresholds_for(experiment: Experiment) -> ClassificationThresholds:
    try:
        config = json.loads(experiment.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    return ClassificationThresholds.from_dict(config.get("thresholds"))
