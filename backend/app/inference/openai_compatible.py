"""OpenAI-compatible API provider.

Measuring *input* likelihood over a hosted chat API is generally impossible:
chat-completions logprobs cover only generated tokens, and most hosted
endpoints do not expose input-token log probabilities. DiffMIA therefore
**never fabricates** likelihood values for such providers.

Scoring works against endpoints that support the legacy ``/completions``
schema with ``echo`` + token ``logprobs`` (typical of self-hosted serving
stacks such as vLLM / llama.cpp / TGI). For those, prompt tokens are echoed
back together with per-token log-probabilities and DiffMIA computes the
teacher-forced NLL over them (dropping tokens without a logprob — usually the
very first, contextless token).

Declare ``supports_logprobs: true`` in ``configs/models.yaml`` only for
endpoints that truly return per-token log-probabilities for the *input*.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from app.core.exceptions import ProviderError
from app.inference.base import (
    LLMProvider,
    ScoreRequest,
    SequenceScore,
    TokenScore,
    perplexity_from_nll,
    raise_logprobs_unsupported,
)

logger = logging.getLogger("diffmia.inference.openai")


class OpenAICompatibleProvider(LLMProvider):
    provider_type = "openai_compatible"

    def __init__(self, name: str, model_id: str, config: dict | None = None) -> None:
        super().__init__(name, model_id, config)
        self.endpoint = (config or {}).get("endpoint", "").rstrip("/")
        self.api_key = (config or {}).get("api_key", "")
        self.api_style = (config or {}).get("api_style", "chat")  # chat | completions
        self.timeout = float((config or {}).get("timeout_seconds", 300))
        self.max_retries = int((config or {}).get("max_retries", 3))
        self.supports_logprobs = bool((config or {}).get("supports_logprobs", False))
        if (config or {}).get("model_version"):
            self.model_version = config["model_version"]
        else:
            self.model_version = self.model_id

    # ── lifecycle ────────────────────────────────────────────────
    def load(self) -> None:
        if not self.endpoint:
            raise ProviderError("Missing 'endpoint' in model configuration.", code="MODEL_CONFIGURATION")
        if not self.api_key:
            raise ProviderError(
                "Missing API key. Set it via the environment variable referenced in configs/models.yaml.",
                code="MODEL_CONFIGURATION",
            )
        if not self.supports_logprobs:
            raise_logprobs_unsupported(
                f"endpoint '{self.endpoint}' is not declared with supports_logprobs: true"
            )
        self.loaded = True

    def health_check(self) -> bool:
        return self.loaded

    def _request_once(self, payload: dict) -> dict:
        url = self.endpoint + ("/completions" if self.api_style == "completions" else "/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"API request timed out after {self.timeout}s.", code="PROVIDER_TIMEOUT", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"API connection error: {exc}", code="PROVIDER_UNAVAILABLE") from exc

        if resp.status_code in (401, 403):
            raise ProviderError("API authentication failed. Check the API key.", code="PROVIDER_AUTH_ERROR")
        if resp.status_code == 429:
            raise ProviderError("API rate limit hit.", code="PROVIDER_RATE_LIMITED")
        if resp.status_code == 400 and "logprobs" in resp.text.lower():
            raise_logprobs_unsupported(
                f"endpoint rejected logprobs request ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"API error {resp.status_code}: {resp.text[:300]}", code="PROVIDER_API_ERROR"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("API returned invalid JSON.", code="PROVIDER_INVALID_RESPONSE") from exc

    def _request_with_retry(self, payload: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._request_once(payload)
            except ProviderError as exc:
                if exc.code not in ("PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMITED", "PROVIDER_UNAVAILABLE", "PROVIDER_API_ERROR"):
                    raise
                last_error = exc
                if exc.code == "PROVIDER_RATE_LIMITED":
                    backoff = min(60.0, 2.0 * (2 ** (attempt - 1)))
                else:
                    backoff = min(30.0, 1.5 * (2 ** (attempt - 1)))
                logger.warning("API request attempt %s/%s failed: %s; retrying in %.1fs", attempt, self.max_retries, exc.code, backoff)
                time.sleep(backoff)
        raise ProviderError(
            f"API request failed after {self.max_retries} attempts: {last_error}",
            code="PROVIDER_UNAVAILABLE",
        )

    # ── scoring ──────────────────────────────────────────────────
    def score_batch(
        self,
        requests: list[ScoreRequest],
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> list[SequenceScore]:
        if self.api_style != "completions":
            raise_logprobs_unsupported(
                "chat-style APIs return logprobs for generated tokens only; "
                "input-token likelihood is not available. Configure an endpoint "
                "with api_style 'completions' that supports echo token logprobs."
            )
        return [self._score_completions(req, token_logs_enabled=token_logs_enabled) for req in requests]

    def _score_completions(self, req: ScoreRequest, *, token_logs_enabled: bool) -> SequenceScore:
        payload = {
            "model": self.model_id,
            "prompt": req.text,
            "echo": True,
            "logprobs": 5,
            "max_tokens": 0,
            "temperature": 0,
            "stream": False,
        }
        data = self._request_with_retry(payload)
        try:
            logprobs = data["choices"][0]["logprobs"]
            tokens = logprobs.get("tokens") or []
            token_logprobs = logprobs.get("token_logprobs") or []
        except (KeyError, IndexError, TypeError):
            raise_logprobs_unsupported("response did not contain token logprobs (echo unsupported)")

        losses: list[float] = []
        token_scores: list[TokenScore] = []
        for idx, raw in enumerate(token_logprobs):
            if idx >= len(tokens):
                break
            if raw is None:
                continue  # contextless first token (no predecessor)
            try:
                logprob = float(raw)
            except (TypeError, ValueError):
                continue
            if logprob == float("-inf"):
                continue
            loss = -logprob
            losses.append(loss)
            if token_logs_enabled:
                token_scores.append(
                    TokenScore(position=len(token_scores), token=str(tokens[idx]), token_id=None, logprob=logprob, loss=loss)
                )
        if not losses:
            raise_logprobs_unsupported(
                "endpoint returned no usable token log-probabilities for the echoed prompt"
            )
        total = sum(losses)
        mean = total / len(losses)
        return SequenceScore(
            token_count=len(losses),
            total_loss=total,
            mean_loss=mean,
            perplexity=perplexity_from_nll(mean),
            truncated=False,
            token_scores=token_scores or None,
        )
