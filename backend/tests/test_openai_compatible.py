from __future__ import annotations

import math

import pytest

from app.inference.base import ScoreRequest, perplexity_from_nll
from app.inference.openai_compatible import OpenAICompatibleProvider


def test_perplexity_uses_natural_log_base():
    assert perplexity_from_nll(2.0) == pytest.approx(math.exp(2.0))
    assert perplexity_from_nll(709.0) == float("inf")
    assert perplexity_from_nll(float("nan")) is None


def test_echoed_logprobs_produce_natural_log_perplexity(monkeypatch):
    provider = OpenAICompatibleProvider(
        "local", "test-model", {"endpoint": "http://localhost:8000", "api_key": "test", "api_style": "completions", "supports_logprobs": True}
    )
    monkeypatch.setattr(
        provider,
        "_request_with_retry",
        lambda payload: {
            "choices": [{"logprobs": {"tokens": ["first", " second", " token"], "token_logprobs": [None, -2.0, -2.0]}}]
        },
    )

    score = provider.score_one(ScoreRequest(text="first second token"))

    assert score.token_count == 2
    assert score.mean_loss == pytest.approx(2.0)
    assert score.perplexity == pytest.approx(math.exp(2.0))
