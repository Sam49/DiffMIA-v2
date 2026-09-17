"""Synchronous experiment pipeline.

Executes one experiment end to end:

    mutations -> inference (original + mutated variants) -> analysis -> status

The function is thread-safe and self-contained (opens its own DB session), so
it is reused by both the in-process background worker and the optional Celery
worker. It runs *synchronously*; callers wrap it in a thread/queue/process.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.analysis.analyzer import analyze_experiment
from app.analysis.classifier import ClassificationThresholds
from app.core.exceptions import ProviderError
from app.db.session import get_session_factory
from app.inference import device as device_util
from app.inference.base import ScoreRequest, SequenceScore
from app.inference.registry import manager as provider_manager
from app.mutation.engine import MutationEngine
from app.models import (
    AnalysisResult,
    DatasetItem,
    Experiment,
    ExperimentLog,
    InferenceCache,
    InferenceRun,
    Mutation,
    TokenLoss,
)
from app.models.enums import ExperimentStage, ExperimentStatus, InferenceStatus, ValidationStatus, Variant
from app.services.cache_service import (
    compute_cache_key,
    dedupe_by_cache_key,
    get_cached,
    input_hash,
    put_cached,
)
from app.services.experiment_service import get_experiment, mark_failed
from app.services.model_service import resolve_definition

logger = logging.getLogger("diffmia.worker")

PROVIDER_STAGES = (ExperimentStage.MUTATION_GENERATION, ExperimentStage.INFERENCE)


def _json_config(experiment: Experiment) -> dict:
    try:
        return json.loads(experiment.config_json or "{}")
    except json.JSONDecodeError:
        return {}


def _log(session: Session, experiment_id: int, message: str, level: str = "INFO", **context) -> None:
    session.add(
        ExperimentLog(
            experiment_id=experiment_id,
            level=level,
            message=message[:2000],
            context_json=json.dumps(context, default=str)[:4000],
        )
    )


def _transition(
    session: Session, experiment_id: int, *, stage: str, message: str, processed: int | None = None
) -> None:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        return
    experiment.current_stage = stage
    experiment.progress_message = message[:2000]
    if processed is not None:
        experiment.processed_items = processed
    session.commit()


def _still_running(session: Session, experiment_id: int) -> bool:
    experiment = session.get(Experiment, experiment_id)
    return experiment is not None and experiment.status == ExperimentStatus.RUNNING.value


def _reset_experiment_data(session: Session, experiment_id: int) -> None:
    """Clear previous run artifacts so a rerun is deterministic."""
    session.execute(delete(TokenLoss).where(TokenLoss.inference_run_id.in_(
        session.query(InferenceRun.id).filter(InferenceRun.experiment_id == experiment_id)
    )))
    session.execute(delete(InferenceRun).where(InferenceRun.experiment_id == experiment_id))
    session.execute(delete(Mutation).where(Mutation.experiment_id == experiment_id))
    session.execute(delete(AnalysisResult).where(AnalysisResult.experiment_id == experiment_id))


def run_experiment(experiment_id: int) -> dict:
    session_factory = get_session_factory()
    session: Session = session_factory()
    started = time.monotonic()
    try:
        experiment = get_experiment(session, experiment_id)
        if experiment.status == ExperimentStatus.CANCELLED.value:
            return {"status": "CANCELLED"}

        # Reset stale artifacts if this is a rerun of a completed experiment.
        if experiment.processed_items > 0 or experiment.status != ExperimentStatus.QUEUED.value:
            _reset_experiment_data(session, experiment_id)
            session.commit()

        experiment.status = ExperimentStatus.RUNNING.value
        experiment.started_at = datetime.now(timezone.utc)
        experiment.current_stage = "processing"
        experiment.progress_message = "Preparing provider…"
        session.commit()

        # Load provider early so configuration errors fail fast with a clear code.
        model = experiment.model  # relationship
        try:
            definition = resolve_definition(model)
            provider = provider_manager.load(model.name, definition)
            provider.loaded  # noqa: B018 - already loaded by manager
        except ProviderError as exc:
            mark_failed(session, experiment_id, error_code=exc.code, error_message=exc.message)
            _log(session, experiment_id, f"Provider load failed: {exc.code}: {exc.message}", level="ERROR")
            session.commit()
            return {"status": "FAILED", "error_code": exc.code}

        experiment.model_version = provider.model_version or experiment.model_version
        _log(session, experiment_id, f"Provider '{model.name}' ({provider.provider_type}) ready.",
             model=model.name, provider=provider.provider_type)

        config = _json_config(experiment)
        token_logs_enabled = bool(config.get("token_losses_enabled", False))
        cache_enabled = bool(config.get("cache_enabled", True))
        thresholds = ClassificationThresholds.from_dict(config.get("thresholds"))

        items = list(
            session.query(DatasetItem)
            .filter(DatasetItem.dataset_id == experiment.dataset_id)
            .order_by(DatasetItem.position)
            .all()
        )
        total = len(items)
        engine = MutationEngine(language="python")

        # ── Mutation generation ───────────────────────────────────
        _transition(session, experiment_id, stage="mutation_generation",
                    message=f"Generating mutations 0/{total}…")
        for done, item in enumerate(items, start=1):
            if not _still_running(session, experiment_id):
                _log(session, experiment_id, "Experiment cancelled during mutation generation.", level="WARN")
                session.commit()
                return {"status": "CANCELLED"}
            snippet_seed = MutationEngine.snippet_seed(experiment.mutation_seed, item.content_hash)
            session.execute(delete(Mutation).where(
                Mutation.experiment_id == experiment_id, Mutation.snippet_id == item.id
            ))
            # Track what we already produced for this snippet so each index
            # contributes distinct evidence instead of repeating one variant.
            produced: set[str] = set()
            for mutation_index in range(1, experiment.mutation_count + 1):
                result = engine.mutate(
                    item.code,
                    seed=snippet_seed,
                    mutation_index=mutation_index,
                    strength=experiment.mutation_strength,
                    avoid=produced,
                )
                if result.status == "VALID":
                    produced.add(result.mutated_code)
                session.add(
                    Mutation(
                        experiment_id=experiment_id,
                        snippet_id=item.id,
                        mutation_index=mutation_index,
                        seed=snippet_seed,
                        original_code=item.code,
                        mutated_code=result.mutated_code,
                        language=item.language,
                        mapping_json=json.dumps(
                            {"seed": result.seed, "mapping": result.mapping, "attempts": result.attempts},
                            ensure_ascii=True,
                        ),
                        validation_status=result.status,
                        validation_score=result.validation_score,
                    )
                )
            session.commit()
            if done % 10 == 0 or done == total:
                _transition(session, experiment_id, stage="mutation_generation",
                            message=f"Generating mutations {done}/{total}…")

        # ── Inference ─────────────────────────────────────────────
        _transition(session, experiment_id, stage="inference", message=f"Inference 0/{total}…",
                    processed=0)
        processed = 0
        for done, item in enumerate(items, start=1):
            if not _still_running(session, experiment_id):
                _log(session, experiment_id, "Experiment cancelled during inference.", level="WARN")
                session.commit()
                return {"status": "CANCELLED"}
            processed += 1

            valid_mutations = (
                session.query(Mutation)
                .filter(
                    Mutation.experiment_id == experiment_id,
                    Mutation.snippet_id == item.id,
                    Mutation.validation_status == ValidationStatus.VALID.value,
                )
                .order_by(Mutation.mutation_index)
                .all()
            )
            requests: list[ScoreRequest] = [
                ScoreRequest(
                    text=item.code,
                    variant=Variant.ORIGINAL.value,
                    mutation_index=None,
                    sample_key=f"{item.dataset_name}:{item.external_id}",
                    metadata=_metadata(item),
                )
            ]
            for mutation in valid_mutations:
                requests.append(
                    ScoreRequest(
                        text=mutation.mutated_code,
                        variant=Variant.MUTATION.value,
                        mutation_index=mutation.mutation_index,
                        sample_key=f"{item.dataset_name}:{item.external_id}",
                        metadata=_metadata(item),
                    )
                )

            session.execute(delete(InferenceRun).where(InferenceRun.experiment_id == experiment_id,
                                                       InferenceRun.snippet_id == item.id))
            session.flush()
            batch_size = max(1, experiment.batch_size)
            for offset in range(0, len(requests), batch_size):
                chunk = requests[offset : offset + batch_size]
                keys = [
                    compute_cache_key(model.name, provider.model_version or model.name, req.text,
                                      {"provider": provider.provider_type, "temperature": experiment.temperature,
                                       "max_tokens": experiment.max_tokens, "logs": token_logs_enabled})
                    for req in chunk
                ]
                # Resolve cache hits; remember misses for one batched call.
                resolved: list[tuple[ScoreRequest, str, SequenceScore | None, bool]] = []
                miss_positions: list[int] = []
                for pos, (req, key) in enumerate(zip(chunk, keys)):
                    cached_payload = get_cached(session, key) if cache_enabled else None
                    if cached_payload:
                        resolved.append((req, key, _score_from_payload(json.loads(cached_payload)), True))
                    else:
                        resolved.append((req, key, None, False))
                        miss_positions.append(pos)

                latency_ms = 0
                if miss_positions:
                    # The same text can legitimately appear twice in one batch (two
                    # snippets sharing a variant). Score it once, fan the result out:
                    # fewer provider calls and no duplicate cache rows.
                    unique_slots, groups = dedupe_by_cache_key(
                        [keys[p] for p in miss_positions]
                    )
                    t0 = time.monotonic()
                    scored = provider.score_batch(
                        [chunk[miss_positions[slot]] for slot in unique_slots],
                        max_tokens=experiment.max_tokens,
                        token_logs_enabled=token_logs_enabled,
                    )
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    for slot, seq_score in zip(unique_slots, scored):
                        _, key, _, _ = resolved[miss_positions[slot]]
                        if cache_enabled:
                            put_cached(session, key, model.name,
                                       input_hash(chunk[miss_positions[slot]].text),
                                       _payload_of(seq_score, token_logs_enabled))
                        for member in groups[slot]:
                            position = miss_positions[member]
                            req, member_key, _, _ = resolved[position]
                            resolved[position] = (req, member_key, seq_score, False)
                # Persist runs (cache hits have zero latency)
                for req, key, score, cache_hit in resolved:
                    assert score is not None
                    _store_run(session, experiment, item, req, score, 0 if cache_hit else latency_ms,
                               token_logs_enabled=token_logs_enabled, cache_hit=cache_hit,
                               model_key=model.name, provider_type=provider.provider_type,
                               model_version=provider.model_version)
            session.commit()
            _transition(session, experiment_id, stage="inference",
                        message=f"Inference {done}/{total}…", processed=processed)

        # ── Analysis ──────────────────────────────────────────────
        _transition(session, experiment_id, stage="analysis",
                    message="Running differential analysis…", processed=processed)
        summary = analyze_experiment(session, session.get(Experiment, experiment_id), thresholds)
        experiment = session.get(Experiment, experiment_id)
        experiment.status = ExperimentStatus.COMPLETED.value
        experiment.current_stage = ExperimentStage.COMPLETED.value
        experiment.progress_message = (
            f"Completed: {summary.get('analyzed_count', 0)} analyzed, "
            f"{summary.get('flagged_count', 0)} flagged in {time.monotonic() - started:.1f}s"
        )
        experiment.completed_at = datetime.now(timezone.utc)
        session.commit()
        return {"status": "COMPLETED", "summary": summary}
    except ProviderError as exc:
        session.rollback()
        mark_failed(session, experiment_id, error_code=exc.code, error_message=exc.message)
        _log(session, experiment_id, f"Pipeline failed: {exc.code}: {exc.message}", level="ERROR")
        session.commit()
        return {"status": "FAILED", "error_code": exc.code, "message": exc.message}
    except Exception as exc:  # noqa: BLE001 - worker must always mark the job terminal
        logger.exception("Experiment %s failed unexpectedly", experiment_id)
        # Roll back first: without it the session is unusable (PendingRollbackError)
        # and the status update itself fails, leaving the run stuck mid-flight with
        # a wall of SQLAlchemy internals as its "error message".
        session.rollback()
        mark_failed(session, experiment_id, error_code="EXPERIMENT_INTERNAL_ERROR",
                    error_message=_summarize_error(exc))
        _log(session, experiment_id, f"Unexpected pipeline error: {exc!r}"[:2000], level="ERROR")
        session.commit()
        return {"status": "FAILED", "error_code": "EXPERIMENT_INTERNAL_ERROR"}
    finally:
        session.close()


def _summarize_error(exc: Exception) -> str:
    """One-line failure reason for the UI (driver chains can be pages long)."""
    raw = " ".join(str(exc).strip().splitlines()[0].split()) if str(exc).strip() else ""
    detail = raw or exc.__class__.__name__
    if len(detail) > 300:
        detail = detail[:297] + "..."
    return f"{type(exc).__name__}: {detail}"


def _metadata(item: DatasetItem) -> dict:
    try:
        return json.loads(item.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}


def _payload_of(score: SequenceScore, with_tokens: bool) -> dict:
    payload = score.as_dict()
    if with_tokens and score.token_scores:
        payload["token_scores"] = [
            {"position": t.position, "token": t.token, "token_id": t.token_id,
             "logprob": t.logprob, "loss": t.loss}
            for t in score.token_scores
        ]
    return payload


def _score_from_payload(payload: dict) -> SequenceScore:
    token_scores = None
    raw_tokens = payload.get("token_scores")
    if raw_tokens:
        from app.inference.base import TokenScore

        token_scores = [TokenScore(**t) for t in raw_tokens]
    return SequenceScore(
        token_count=int(payload.get("token_count", 0)),
        total_loss=float(payload.get("total_loss", 0.0)),
        mean_loss=float(payload.get("mean_loss", 0.0)),
        perplexity=payload.get("perplexity"),
        truncated=bool(payload.get("truncated", False)),
        token_scores=token_scores,
    )


def _store_run(
    session: Session,
    experiment: Experiment,
    item: DatasetItem,
    request: ScoreRequest,
    score: SequenceScore,
    latency_ms: int,
    *,
    token_logs_enabled: bool,
    cache_hit: bool,
    model_key: str = "",
    provider_type: str = "",
    model_version: str = "",
) -> None:
    status = InferenceStatus.SUCCESS.value
    error_code = ""
    error_message = ""
    if score.error_code:
        status = InferenceStatus.FAILED.value
        error_code = score.error_code
        error_message = score.error_message
    run = InferenceRun(
        experiment_id=experiment.id,
        snippet_id=item.id,
        variant=request.variant,
        mutation_index=request.mutation_index,
        model_key=model_key,
        provider=provider_type,
        model_version=model_version,
        status=status,
        token_count=score.token_count,
        total_loss=score.total_loss,
        mean_loss=score.mean_loss,
        perplexity=score.perplexity,
        cache_hit=cache_hit,
        latency_ms=latency_ms,
        truncated=score.truncated,
        error_code=error_code,
        error_message=error_message,
    )
    session.add(run)
    session.flush()
    if token_logs_enabled and score.token_scores:
        for token in score.token_scores:
            session.add(
                TokenLoss(
                    inference_run_id=run.id,
                    position=token.position,
                    token=token.token[:200],
                    token_id=token.token_id,
                    logprob=token.logprob,
                    loss=token.loss,
                )
            )
