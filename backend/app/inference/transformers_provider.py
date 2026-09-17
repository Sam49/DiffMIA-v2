"""Local Hugging Face ``transformers`` provider (Llama family, CodeLlama, ...).

Heavy dependencies (torch/transformers) are imported lazily so the rest of
DiffMIA — including DEMO MODE with the mock provider — runs without them.

The model is cached per (model_id, dtype, device) and shared across
experiments to avoid repeated reloads (see the ``unload`` endpoint for an
explicit release).
"""
from __future__ import annotations

import logging
import threading

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.inference import device as device_util
from app.inference.base import (
    LLMProvider,
    ScoreRequest,
    SequenceScore,
    TokenScore,
    perplexity_from_nll,
    raise_logprobs_unsupported,
)

logger = logging.getLogger("diffmia.inference.transformers")

# Model cache shared process-wide: key -> (model, tokenizer)
_MODEL_CACHE: dict[str, tuple] = {}
_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE_MAX = 2  # keep memory bounded; more models must be unloaded explicitly

_VOCAB_FACTOR_BYTES = 4  # fp32 element size (CPU / conservative)


class TransformersProvider(LLMProvider):
    provider_type = "transformers"
    supports_logprobs = True

    def __init__(self, name: str, model_id: str, config: dict | None = None) -> None:
        super().__init__(name, model_id, config)
        self._model = None
        self._tokenizer = None
        self._device = ""

    # ── lifecycle ────────────────────────────────────────────────
    def _imports(self) -> tuple:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            import accelerate  # noqa: F401
        except ImportError as exc:
            raise ProviderError(
                "The 'transformers' provider needs optional dependencies: "
                "install them with `pip install -r backend/requirements-transformers.txt`.",
                code="PROVIDER_DEPENDENCY",
                status_code=502,
            ) from exc
        import torch
        import transformers

        return torch, transformers

    def load(self) -> None:
        if self.loaded:
            return
        torch, transformers = self._imports()
        settings = get_settings()
        self._device = device_util.detect_device(self.config.get("device") or settings.device)
        torch_dtype = self.config.get("torch_dtype") or settings.torch_dtype

        dtype = None
        if torch_dtype in ("float16", "fp16"):
            dtype = torch.float16
        elif torch_dtype in ("bfloat16", "bf16"):
            dtype = torch.bfloat16
        elif torch_dtype in ("float32", "fp32"):
            dtype = torch.float32

        key = f"{self.model_id}|{dtype}|{self._device}"
        with _MODEL_CACHE_LOCK:
            if key in _MODEL_CACHE:
                self._model, self._tokenizer = _MODEL_CACHE[key]
                self.loaded = True
                return

        hf_token = self.config.get("hf_token") or settings.hf_token or None
        kwargs: dict = {"cache_dir": settings.model_cache_dir, "token": hf_token}
        if self.config.get("trust_remote_code"):
            kwargs["trust_remote_code"] = True
        try:
            tokenizer = transformers.AutoTokenizer.from_pretrained(self.model_id, **kwargs)
            model_kwargs: dict = dict(kwargs)
            if dtype is not None:
                model_kwargs["torch_dtype"] = dtype
            if self.config.get("load_in_8bit"):
                try:
                    from transformers import BitsAndBytesConfig

                    model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
                except Exception:
                    raise ProviderError(
                        "load_in_8bit requires bitsandbytes. Install the optional dependency.",
                        code="PROVIDER_DEPENDENCY",
                    )
            if self._device in ("cuda", "auto") and not self.config.get("load_in_8bit"):
                model_kwargs["device_map"] = "auto"
            model = transformers.AutoModelForCausalLM.from_pretrained(self.model_id, **model_kwargs)
            if self._device not in ("cuda", "auto") and getattr(model, "device", None) is None:
                model = model.to(self._device)
        except ProviderError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise ProviderError(
                f"Model '{self.model_id}' could not be loaded: {exc}",
                code="MODEL_UNAVAILABLE",
                status_code=502,
            ) from exc

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model.eval()

        with _MODEL_CACHE_LOCK:
            if len(_MODEL_CACHE) >= _MODEL_CACHE_MAX:
                oldest_key = next(iter(_MODEL_CACHE))
                del _MODEL_CACHE[oldest_key]
            _MODEL_CACHE[key] = (model, tokenizer)
        self._model, self._tokenizer = model, tokenizer
        self.model_version = (
            f"{getattr(model.config, '_name_or_path', self.model_id)}@transformers-{transformers.__version__}"
        )
        self.loaded = True

    def unload(self) -> None:
        torch, _ = self._imports()
        with _MODEL_CACHE_LOCK:
            keys = [k for k in _MODEL_CACHE if k.startswith(f"{self.model_id}|")]
            for k in keys:
                del _MODEL_CACHE[k]
        self._model = None
        self._tokenizer = None
        self.loaded = False
        if self._device in ("cuda",):
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    def health_check(self) -> bool:
        return self.loaded

    # ── scoring ──────────────────────────────────────────────────
    def _token_budget(self) -> int:
        if self._device == "cuda":
            return 6000
        return 2000

    def score_batch(
        self,
        requests: list[ScoreRequest],
        *,
        max_tokens: int = 4096,
        token_logs_enabled: bool = False,
    ) -> list[SequenceScore]:
        if not self.loaded:
            self.load()
        if not requests:
            return []
        torch, transformers = self._imports()
        if not self.supports_logprobs:  # never reached for transformers, kept for safety
            raise_logprobs_unsupported("provider reports no logprobs support")

        tokenizer = self._tokenizer
        model = self._model

        # Tokenize once per request with explicit truncation bookkeeping.
        per_token_counts: list[int] = []
        encoded_list: list = []
        for req in requests:
            if not req.text.strip():
                raise ProviderError("Cannot score an empty code snippet.", code="INVALID_INPUT")
            enc = tokenizer(req.text, return_tensors="pt", add_special_tokens=True, truncation=True, max_length=max_tokens)
            full_len = len(tokenizer(req.text, add_special_tokens=True).input_ids)
            per_token_counts.append(full_len)
            encoded_list.append(enc)

        results: list[SequenceScore] = [None] * len(requests)  # type: ignore[list-item]

        # Chunk requests so a single forward pass stays within a memory budget.
        budget = self._token_budget()
        chunk: list[int] = []
        chunk_tokens = 0
        for idx, enc in enumerate(encoded_list):
            size = enc["input_ids"].shape[1]
            if chunk and chunk_tokens + size > budget:
                self._score_chunk(requests, encoded_list, chunk, token_logs_enabled, model, tokenizer, results, per_token_counts)
                chunk = []
                chunk_tokens = 0
            chunk.append(idx)
            chunk_tokens += size
        if chunk:
            self._score_chunk(requests, encoded_list, chunk, token_logs_enabled, model, tokenizer, results, per_token_counts)
        return results

    def _score_chunk(self, requests, encoded_list, indices, token_logs_enabled, model, tokenizer, results, full_counts) -> None:
        import torch

        special_ids = set(tokenizer.all_special_ids)
        device = next(model.parameters()).device

        batch_enc = tokenizer.pad(
            [encoded_list[i] for i in indices], return_tensors="pt", pad_to_multiple_of=None
        )
        input_ids = batch_enc["input_ids"].to(device)
        attention = batch_enc["attention_mask"].to(device)

        with torch.inference_mode():
            outputs = model(input_ids=input_ids, attention_mask=attention)
            logits = outputs.logits  # [B, T, V]

        # Shift: token t (t>=1) is scored from logits at t-1.
        shift_logits = logits[:, :-1, :]  # [B, T-1, V]
        targets = input_ids[:, 1:]  # [B, T-1]
        log_probs = torch.log_softmax(shift_logits, dim=-1)
        token_losses = -log_probs.gather(dim=-1, index=targets.unsqueeze(-1)).squeeze(-1)
        # Mask special/pad target tokens
        valid = ~torch.isin(targets, torch.tensor(list(special_ids), device=targets.device))
        masked_losses = token_losses.masked_fill(~valid, 0.0)

        for row, idx in enumerate(indices):
            mask = valid[row]
            count = int(mask.sum().item())
            total = float(masked_losses[row].sum().item())
            mean = total / count if count else 0.0
            truncated = full_counts[idx] > input_ids.shape[1]
            token_scores = None
            if token_logs_enabled:
                token_scores = []
                target_row = targets[row]
                losses_row = token_losses[row]
                for col in range(targets.shape[1]):
                    if not bool(mask[col].item()):
                        continue
                    token_id = int(target_row[col].item())
                    piece = tokenizer.decode([token_id])
                    loss = float(losses_row[col].item())
                    token_scores.append(
                        TokenScore(position=col, token=piece, token_id=token_id, logprob=-loss, loss=loss)
                    )
            results[idx] = SequenceScore(
                token_count=count,
                total_loss=total,
                mean_loss=mean,
                perplexity=perplexity_from_nll(mean),
                truncated=truncated,
                token_scores=token_scores,
            )
        del logits, shift_logits, log_probs, token_losses, masked_losses
        if device.type == "cuda":
            torch.cuda.empty_cache()

    # ── generation (utility; not used by the contamination pipeline) ──
    def generate(self, prompt: str, *, max_new_tokens: int = 128, temperature: float = 0.0) -> str:
        if not self.loaded:
            self.load()
        import torch

        tokenizer = self._tokenizer
        model = self._model
        enc = tokenizer(prompt, return_tensors="pt").to(next(model.parameters()).device)
        with torch.inference_mode():
            out = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=temperature or None,
                pad_token_id=tokenizer.pad_token_id,
            )
        return tokenizer.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
