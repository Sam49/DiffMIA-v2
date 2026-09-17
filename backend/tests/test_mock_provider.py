from __future__ import annotations

import math

import pytest

from app.inference.base import ScoreRequest
from app.inference.mock import MockLLMProvider

CODE = "def solution(numbers):\n    total = 0\n    for number in numbers:\n        total += number\n    return total\n"


def _provider() -> MockLLMProvider:
    provider = MockLLMProvider("demo", "mock-1", {"memorization_ratio": 0.5, "memorization_delta": 0.9})
    provider.load()
    return provider


def test_deterministic_scores():
    provider = _provider()
    req = ScoreRequest(text=CODE, variant="original", sample_key="ds:sum_001", metadata={})
    first = provider.score_one(req, token_logs_enabled=True)
    second = provider.score_one(req, token_logs_enabled=True)
    assert first.total_loss == second.total_loss
    assert first.mean_loss == second.mean_loss
    assert first.token_count == second.token_count
    assert [t.logprob for t in first.token_scores] == [t.logprob for t in second.token_scores]


def test_memorized_original_gets_lower_loss_than_mutations():
    provider = _provider()
    original = provider.score_one(
        ScoreRequest(text=CODE, variant="original", sample_key="ds:mem_1", metadata={"memorized": True})
    )
    mutation_scores = [
        provider.score_one(
            ScoreRequest(text=CODE.replace("numbers", "values").replace("total", "result"),
                         variant="mutation", mutation_index=i, sample_key="ds:mem_1",
                         metadata={"memorized": True})
        )
        for i in range(1, 6)
    ]
    assert original.mean_loss < min(m.mean_loss for m in mutation_scores)
    mut_mean = sum(m.mean_loss for m in mutation_scores) / len(mutation_scores)
    ci = (mut_mean - original.mean_loss) / abs(original.mean_loss)
    assert ci > 0.2


def test_non_memorized_items_have_near_zero_ci():
    provider = _provider()
    original = provider.score_one(
        ScoreRequest(text=CODE, variant="original", sample_key="ds:norm_1", metadata={"memorized": False})
    )
    mutated = [
        provider.score_one(
            ScoreRequest(text=CODE.replace("numbers", "values").replace("total", "result"),
                         variant="mutation", mutation_index=i, sample_key="ds:norm_1",
                         metadata={"memorized": False})
        )
        for i in range(1, 6)
    ]
    mut_mean = sum(m.mean_loss for m in mutated) / len(mutated)
    ci = (mut_mean - original.mean_loss) / abs(original.mean_loss)
    assert abs(ci) < 0.12


def test_token_scores_and_counts_consistent():
    provider = _provider()
    req = ScoreRequest(text=CODE, variant="original", sample_key="ds:x", metadata={"memorized": True})
    score = provider.score_one(req, token_logs_enabled=True)
    assert score.token_count > 5
    assert score.token_scores is not None
    assert len(score.token_scores) == score.token_count
    total_from_tokens = sum(t.loss for t in score.token_scores)
    assert abs(total_from_tokens - score.total_loss) < 1e-6
    assert score.perplexity == pytest.approx(math.exp(score.mean_loss))


def test_truncation_reported():
    provider = _provider()
    req = ScoreRequest(text=CODE * 200, variant="original", sample_key="ds:long", metadata={})
    score = provider.score_one(req, max_tokens=16)
    assert score.truncated is True
    assert score.token_count <= 16
