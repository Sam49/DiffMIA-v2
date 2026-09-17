"""Unified inference interface.

Providers implement :class:`LLMProvider`. The core analysis engine only ever
depends on this interface, so new backends (local, API, custom) can be added
without touching the pipeline.

Token-level loss contract
-------------------------
Loss is always measured as teacher-forced negative log likelihood (NLL) over
*content* tokens: token ``t`` is scored by the model's log-probability given
the full preceding context. Prompt/special tokens, padding and truncation are
handled explicitly:

* the very first token has no predecessor and is never scored;
* special tokens (BOS/EOS) and padding are excluded from the loss;
* if an input exceeds ``max_tokens`` it is truncated and reported as such
  (``truncated=True``) so callers never silently compare truncated vs full
  sequences.

No provider may fabricate likelihood values: if token log-probabilities are
not available, the provider raises :class:`~app.core.exceptions.ProviderError`
with code ``LOGPROBS_UNSUPPORTED``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math

from app.core.exceptions import ProviderError


def perplexity_from_nll(mean_loss: float) -> float | None:
    """Convert a mean natural-log NLL to perplexity without overflow.

    Every provider reports token log-probabilities in natural-log space, so
    perplexity is ``exp(mean_nll)``.  Keeping the conversion here prevents
    provider-specific bases from silently producing incomparable values.
    """
    if not math.isfinite(mean_loss):
        return None
    # exp(709.78...) is the largest finite IEEE-754 double precision value.
    return math.exp(mean_loss) if mean_loss < 709.0 else float("inf")


@dataclass
class TokenScore:
    position: int
    token: str
    token_id: int | None
    logprob: float
    loss: float


@dataclass
class SequenceScore:
    token_count: int
    total_loss: float
    mean_loss: float
    perplexity: float | None = None
    truncated: bool = False
    token_scores: list[TokenScore] | None = None
    error_code: str = ""
    error_message: str = ""

    def as_dict(self) -> dict:
        return {
            "token_count": self.token_count,
            "total_loss": self.total_loss,
            "mean_loss": self.mean_loss,
            "perplexity": self.perplexity,
            "truncated": self.truncated,
        }


@dataclass
class ScoreRequest:
    text: str
    variant: str = "original"  # original | mutation
    mutation_index: int | None = None
    sample_key: str = ""
    metadata: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Interface every inference backend must implement."""

    provider_type: str = "base"
    supports_logprobs: bool = True
    is_mock: bool = False
    batching: bool = True

    def __init__(self, name: str, model_id: str, config: dict | None = None) -> None:
        self.name = name
        self.model_id = model_id
        self.config = config or {}
        self.loaded = False
        self.last_error = ""
        self.model_version = self.config.get("model_version", "")

    # ── lifecycle ────────────────────────────────────────────────
    @abstractmethod
    def load(self) -> None:
        """Load the underlying model / connection. Raise ProviderError on failure."""

    def unload(self) -> None:
        """Release resources. Default: no-op."""
        self.loaded = False

    def health_check(self) -> bool:
        """Lightweight availability probe. Defaults to load state."""
        return self.loaded

    # ── scoring ──────────────────────────────────────────────────
    @abstractmethod
    def score_batch(
        self,
        requests: list[ScoreRequest],
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> list[SequenceScore]:
        """Return one :class:`SequenceScore` per request (same order)."""

    def score_one(
        self,
        request: ScoreRequest,
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> SequenceScore:
        return self.score_batch([request], max_tokens=max_tokens, token_logs_enabled=token_logs_enabled)[0]

    def describe(self) -> dict:
        return {
            "name": self.name,
            "provider": self.provider_type,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "supports_logprobs": self.supports_logprobs,
            "is_mock": self.is_mock,
            "batching": self.batching,
            "loaded": self.loaded,
        }


def raise_logprobs_unsupported(detail: str) -> None:
    raise ProviderError(
        f"This API/model does not expose token log probabilities ({detail}). "
        "Differential-loss analysis requires per-token logprobs and the system "
        "will not fabricate likelihood values. Configure a model that supports "
        "logprobs (e.g. local transformers) or set 'supports_logprobs: true' "
        "in configs/models.yaml only when the endpoint truly returns them.",
        code="LOGPROBS_UNSUPPORTED",
        status_code=502,
    )
