"""MockLLMProvider — deterministic synthetic scoring.

Purpose
-------
Lets the *entire* product run immediately in DEMO MODE: no GPU, no Hugging
Face token, no paid API and no model download. Loss values are synthetic but
fully deterministic: identical inputs always produce identical outputs, so
experiments remain reproducible and cacheable.

How the synthetic signal works
------------------------------
A snippet is treated as "memorized" when its metadata flag ``memorized`` is
explicitly set, otherwise by a stable hash of the snippet key compared with
``memorization_ratio``. Memorized originals receive a lower per-token loss
(shifted by ``memorization_delta``), producing the differential-loss pattern
the real pipeline detects. Non-memorized items get a small, roughly symmetric
difference, so the CI distribution includes both near-zero and clearly
positive values — demonstrating classification without any real model.

This provider is clearly marked (``is_mock=True``) and the UI displays
"DEMO MODE" whenever an experiment uses it.
"""
from __future__ import annotations

import hashlib
import math
import random
import re

from app.inference.base import LLMProvider, ScoreRequest, SequenceScore, TokenScore, perplexity_from_nll

_TOKEN_RE = re.compile(r"\s+|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|.")


def _text_hash(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


class MockLLMProvider(LLMProvider):
    provider_type = "mock"
    supports_logprobs = True
    is_mock = True

    def __init__(self, name: str, model_id: str, config: dict | None = None) -> None:
        super().__init__(name, model_id, config)
        self.memorization_ratio = float(self.config.get("memorization_ratio", 0.35))
        self.memorization_delta = float(self.config.get("memorization_delta", 0.9))
        self.model_version = self.config.get("model_version", "mock-2.0")

    # ── lifecycle ────────────────────────────────────────────────
    def load(self) -> None:
        # Nothing to load: the mock is always available.
        self.loaded = True

    def health_check(self) -> bool:
        return True

    # ── scoring ──────────────────────────────────────────────────
    def _is_memorized(self, sample_key: str, metadata: dict) -> bool:
        if "memorized" in metadata:
            return bool(metadata["memorized"])
        return (_text_hash(f"memorized::{sample_key}") % 1000) / 1000.0 < self.memorization_ratio

    def score_batch(
        self,
        requests: list[ScoreRequest],
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> list[SequenceScore]:
        scores: list[SequenceScore] = []
        for request in requests:
            text = request.text
            tokens = _tokenize(text)[:max_tokens]
            truncated = len(_tokenize(text)) > max_tokens
            is_original = request.variant == "original"
            memorized = self._is_memorized(request.sample_key, request.metadata)

            # The synthetic model has a snippet-level latent difficulty shared by
            # the original and every mutation (seeded by the stable sample key),
            # plus per-text jitter so different variants are not identical.
            key_rng = random.Random(_text_hash(f"key::{request.sample_key}::{self.name}"))
            text_rng = random.Random(_text_hash(f"text::{text}::{self.name}"))
            latent = key_rng.uniform(1.6, 3.0)
            if memorized and is_original:
                # The memorized original is systematically *easier* than the latent
                # difficulty of its never-seen mutations.
                base = max(latent - self.memorization_delta - key_rng.uniform(0.0, 0.25), 0.25)
            elif memorized:
                # Its mutations sit at (or slightly above) the latent difficulty.
                base = latent + text_rng.uniform(0.05, 0.15)
            else:
                # Non-memorized items: original and mutations drawn from the same
                # latent difficulty -> CI near zero (null distribution).
                base = latent + text_rng.uniform(-0.05, 0.05)

            raw = [max(0.02, base + text_rng.gauss(0.0, 0.3)) for _ in tokens]
            mean = sum(raw) / len(raw) if raw else 0.0
            # Normalize so the realised mean exactly equals the target base
            if mean > 0:
                shift = base - mean
                raw = [max(0.02, v + shift) for v in raw]
            mean = sum(raw) / len(raw) if raw else base
            total = sum(raw)
            token_scores = None
            if token_logs_enabled:
                token_scores = []
                for pos, (token, loss) in enumerate(zip(tokens, raw)):
                    logprob = -loss
                    token_scores.append(
                        TokenScore(position=pos, token=token, token_id=None, logprob=logprob, loss=loss)
                    )
            scores.append(
                SequenceScore(
                    token_count=len(tokens),
                    total_loss=total,
                    mean_loss=mean,
                    perplexity=perplexity_from_nll(mean),
                    truncated=truncated,
                    token_scores=token_scores,
                )
            )
        return scores
