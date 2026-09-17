from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)

    # Reproducibility fingerprint
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model_version: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Mutation configuration
    mutation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    mutation_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=42)
    mutation_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    mutation_strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="identifier_rename")

    # Inference configuration
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    device: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Execution state
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED", index=True)
    current_stage: Mapped[str] = mapped_column(String(48), nullable=False, default="queued")
    progress_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    model: Mapped["ModelInfo"] = relationship()  # noqa: F821
    dataset: Mapped["Dataset"] = relationship()  # noqa: F821


class Mutation(Base):
    __tablename__ = "mutations"
    __table_args__ = (
        Index("ix_mutations_exp_snippet_index", "experiment_id", "snippet_id", "mutation_index", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    snippet_id: Mapped[int] = mapped_column(ForeignKey("dataset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    mutation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    mutated_code: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="python")
    mapping_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID")
    validation_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InferenceRun(Base):
    __tablename__ = "inference_runs"
    __table_args__ = (
        Index("ix_inference_exp_snippet_variant", "experiment_id", "snippet_id", "variant", "mutation_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    snippet_id: Mapped[int] = mapped_column(ForeignKey("dataset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(16), nullable=False)  # original | mutation
    mutation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model_version: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCESS")
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    perplexity: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(default=False, nullable=False)

    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TokenLoss(Base):
    __tablename__ = "token_losses"
    __table_args__ = (
        Index("ix_token_losses_run", "inference_run_id", "position", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inference_run_id: Mapped[int] = mapped_column(ForeignKey("inference_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logprob: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    loss: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        Index("ix_analysis_experiment_snippet", "experiment_id", "snippet_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    snippet_id: Mapped[int] = mapped_column(ForeignKey("dataset_items.id", ondelete="CASCADE"), nullable=False, index=True)

    original_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mean_mutation_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_mutation_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    std_mutation_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    mutation_count_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mutation_count_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contamination_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    abs_loss_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    rel_loss_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score_global: Mapped[float | None] = mapped_column(Float, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_rank: Mapped[float | None] = mapped_column(Float, nullable=True)

    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="LOW_EVIDENCE")
    classification_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    flagged: Mapped[bool] = mapped_column(default=False, nullable=False)
    extra_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    experiment: Mapped[Experiment] = relationship()
    snippet: Mapped["DatasetItem"] = relationship()  # noqa: F821


class ExperimentLog(Base):
    __tablename__ = "experiment_logs"
    __table_args__ = (
        Index("ix_experiment_logs_exp_created", "experiment_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
