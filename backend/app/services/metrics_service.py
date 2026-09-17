"""Observability metrics (requests, latency, job counts, GPU)."""
from __future__ import annotations

import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Experiment, InferenceRun
from app.models.enums import ExperimentStatus

_started = time.monotonic()
_lock = threading.Lock()
_requests_total = 0
_requests_by_path: dict[str, int] = {}


def record_request(path: str) -> None:
    global _requests_total
    with _lock:
        _requests_total += 1
        _requests_by_path[path] = _requests_by_path.get(path, 0) + 1


def snapshot(db: Session) -> dict:
    with _lock:
        requests_total = _requests_total
        requests_by_path = dict(_requests_by_path)
    statuses = db.execute(select(Experiment.status, func.count()).group_by(Experiment.status)).all()
    counts = {s: int(c) for s, c in statuses}
    latency = db.execute(
        select(func.avg(InferenceRun.latency_ms)).where(InferenceRun.latency_ms.is_not(None))
    ).scalar_one_or_none()
    cache_hits = db.execute(
        select(func.count()).select_from(InferenceRun).where(InferenceRun.cache_hit.is_(True))
    ).scalar_one()
    runs_total = db.execute(select(func.count()).select_from(InferenceRun)).scalar_one()

    try:
        from app.inference import device as device_util

        gpu = device_util.gpu_status()
    except Exception:
        gpu = {}

    return {
        "uptime_seconds": round(time.monotonic() - _started, 1),
        "requests_total": requests_total,
        "requests_by_path": requests_by_path,
        "active_experiments": counts.get(ExperimentStatus.RUNNING.value, 0),
        "queued_experiments": counts.get(ExperimentStatus.QUEUED.value, 0),
        "completed_experiments": counts.get(ExperimentStatus.COMPLETED.value, 0),
        "failed_experiments": counts.get(ExperimentStatus.FAILED.value, 0),
        "cancelled_experiments": counts.get(ExperimentStatus.CANCELLED.value, 0),
        "inference_runs_total": runs_total,
        "cache_hits": cache_hits,
        "cache_misses": max(runs_total - cache_hits, 0),
        "avg_inference_latency_ms": round(float(latency), 1) if latency is not None else None,
        "gpu": gpu,
    }
