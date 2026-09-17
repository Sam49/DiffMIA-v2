from __future__ import annotations

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    database: str
    worker: str
    request_id: str


class MetricPoint(BaseModel):
    name: str
    value: float | int
    unit: str = ""


class MetricsOut(BaseModel):
    uptime_seconds: float
    requests_total: int
    requests_by_path: dict[str, int]
    active_experiments: int
    queued_experiments: int
    completed_experiments: int
    failed_experiments: int
    cancelled_experiments: int
    inference_runs_total: int
    cache_hits: int
    cache_misses: int
    avg_inference_latency_ms: float | None = None
    gpu: dict
