"""DeepSeek API provider.

DeepSeek exposes an OpenAI-compatible *chat* API which does not return
per-token log-probabilities for input content. DiffMIA never approximates or
fabricates likelihood values, so experiments fail fast with a clear
``LOGPROBS_UNSUPPORTED`` error unless the entry in ``configs/models.yaml``
explicitly declares ``supports_logprobs: true`` (only valid for DeepSeek
endpoints / gateways that genuinely expose input logprobs).
"""
from __future__ import annotations

from app.core.exceptions import ProviderError
from app.inference.base import ScoreRequest, SequenceScore
from app.inference.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    provider_type = "deepseek"

    def __init__(self, name: str, model_id: str, config: dict | None = None) -> None:
        config = dict(config or {})
        config.setdefault("api_style", "chat")
        config.setdefault("endpoint", "https://api.deepseek.com")
        # DeepSeek chat API has no input-token logprobs; require an explicit opt-in.
        config.setdefault("supports_logprobs", False)
        super().__init__(name, model_id, config)

    def load(self) -> None:
        if not self.supports_logprobs:
            raise ProviderError(
                "The DeepSeek chat API does not expose input-token log probabilities. "
                "Differential-loss analysis cannot run against it without fabricated "
                "values, which DiffMIA refuses to produce. Set 'supports_logprobs: true' "
                "in configs/models.yaml only if your endpoint truly supports them.",
                code="LOGPROBS_UNSUPPORTED",
                status_code=502,
            )
        super().load()

    def score_batch(
        self,
        requests: list[ScoreRequest],
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> list[SequenceScore]:
        raise ProviderError(
            "DeepSeek scoring requires input-token logprobs, which the chat API does not provide.",
            code="LOGPROBS_UNSUPPORTED",
            status_code=502,
        )
