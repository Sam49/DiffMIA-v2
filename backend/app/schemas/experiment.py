from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import ExperimentStatus
from app.schemas.common import ORMModel
from app.schemas.dataset import DatasetItemOut
from app.schemas.model import ModelOut


class ThresholdConfig(BaseModel):
    """Statistical thresholds used by the classifier (configurable)."""

    ci_possible: float = 0.15
    z_possible: float = 2.0
    ci_high: float = 0.35
    z_high: float = 3.5
    ci_elevated: float = 0.05
    z_elevated: float = 1.3
    min_items_for_baseline: int = 3


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    dataset_id: int = Field(gt=0)
    model_id: int = Field(gt=0)
    mutation_count: int | None = Field(default=None, ge=1, le=20)
    mutation_seed: int | None = None
    mutation_strength: float | None = Field(default=None, gt=0.0, le=1.0)
    mutation_strategy: str = Field(default="identifier_rename")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    batch_size: int | None = Field(default=None, ge=1, le=64)
    device: str | None = Field(default=None, max_length=32)
    token_losses_enabled: bool | None = None
    cache_enabled: bool | None = None
    thresholds: ThresholdConfig | None = None


class ExperimentOut(ORMModel):
    id: int
    name: str
    description: str
    created_by: int
    model_id: int
    dataset_id: int
    dataset_hash: str
    model_version: str
    mutation_count: int
    mutation_seed: int
    mutation_strength: float
    mutation_strategy: str
    temperature: float
    max_tokens: int
    batch_size: int
    device: str
    config_json: str
    status: ExperimentStatus
    current_stage: str
    progress_message: str
    total_items: int
    processed_items: int
    error_code: str
    error_message: str
    created_at: object | None = None
    started_at: object | None = None
    completed_at: object | None = None


class ExperimentDetail(ExperimentOut):
    model: ModelOut | None = None
    dataset: object | None = None
    created_by_user: str = ""


class ExperimentList(BaseModel):
    items: list[ExperimentOut]
    total: int


class AnalysisOut(BaseModel):
    """One snippet's differential analysis, joined with snippet info."""

    snippet_id: int
    external_id: str
    dataset_name: str
    problem_statement: str
    code: str
    language: str
    metadata_json: str

    original_loss: float | None = None
    original_token_count: int | None = None
    mean_mutation_loss: float | None = None
    median_mutation_loss: float | None = None
    std_mutation_loss: float | None = None
    mutation_count_used: int = 0
    mutation_count_requested: int = 0

    contamination_index: float | None = None
    abs_loss_delta: float | None = None
    rel_loss_delta: float | None = None
    z_score: float | None = None
    z_score_global: float | None = None
    effect_size: float | None = None
    percentile_rank: float | None = None

    classification: str
    classification_reason: str
    flagged: bool
    extra_json: str = "{}"


class Distribution(BaseModel):
    label: str
    values: list[float]
    histogram_x: list[float]
    histogram_y: list[int]
    kde_x: list[float]
    kde_y: list[float]


class ExperimentStats(BaseModel):
    analyzed_count: int
    flagged_count: int
    high_signal_count: int
    low_evidence_count: int
    failed_snippets: int
    mean_ci: float | None = None
    median_ci: float | None = None
    std_ci: float | None = None
    mean_z: float | None = None
    mean_original_loss: float | None = None
    mean_mutation_loss: float | None = None
    epsilon: float = 1e-9


class ResultsBundle(BaseModel):
    experiment: ExperimentDetail
    stats: ExperimentStats
    analyses: list[AnalysisOut]
    classifications: dict[str, int]
    distributions: dict[str, Distribution]
