"""Provider registry.

Model definitions live in ``configs/models.yaml``. Environment references of
the form ``${VAR}`` / ``${VAR:-default}`` are resolved at load time so secrets
are never stored in code, config files committed to git, or the database.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.inference.base import LLMProvider
from app.inference.deepseek import DeepSeekProvider
from app.inference.mock import MockLLMProvider
from app.inference.openai_compatible import OpenAICompatibleProvider
from app.inference.transformers_provider import TransformersProvider

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def resolve_env_refs(value):
    """Recursively resolve ``${VAR}`` / ``${VAR:-default}`` references."""
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            var, default = match.group(1), match.group(2)
            import os

            resolved = os.environ.get(var)
            if resolved is None:
                resolved = default
            return resolved if resolved is not None else ""

        return _ENV_REF.sub(repl, value)
    if isinstance(value, dict):
        return {k: resolve_env_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_refs(v) for v in value]
    return value


def load_model_definitions() -> OrderedDict[str, dict]:
    """Load and env-resolve every model entry from configs/models.yaml."""
    path = Path(get_settings().models_config_path)
    if not path.exists():
        return OrderedDict()
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    definitions: OrderedDict[str, dict] = OrderedDict()
    for name, entry in (raw.get("models") or {}).items():
        resolved = resolve_env_refs(dict(entry or {}))
        resolved["name"] = name
        resolved.setdefault("display_name", name)
        resolved.setdefault("description", "")
        resolved.setdefault("model_id", name)
        definitions[name] = resolved
    return definitions


def get_definition(name: str) -> dict:
    definitions = load_model_definitions()
    if name not in definitions:
        raise ProviderError(
            f"Model '{name}' is not registered in configs/models.yaml.", code="MODEL_CONFIGURATION"
        )
    return definitions[name]


def create_provider(name: str, definition: dict | None = None) -> LLMProvider:
    """Instantiate a provider from a model definition."""
    definition = definition or get_definition(name)
    provider_type = (definition.get("provider") or "").lower()
    model_id = definition.get("model_id") or name
    config = dict(definition)
    config.pop("name", None)
    if provider_type == "mock":
        return MockLLMProvider(name, model_id, config)
    if provider_type == "transformers":
        return TransformersProvider(name, model_id, config)
    if provider_type in ("openai_compatible", "openai"):
        return OpenAICompatibleProvider(name, model_id, config)
    if provider_type in ("deepseek", "deepseek-coder"):
        return DeepSeekProvider(name, model_id, config)
    raise ProviderError(
        f"Unknown provider type '{provider_type}' for model '{name}'. "
        "Supported: mock, transformers, openai_compatible, deepseek.",
        code="MODEL_CONFIGURATION",
    )


def provider_capabilities(name: str) -> dict:
    """Static capability flags without loading the model."""
    definition = get_definition(name)
    provider_type = (definition.get("provider") or "").lower()
    is_mock = provider_type == "mock"
    supports_logprobs = is_mock or provider_type == "transformers" or bool(
        definition.get("supports_logprobs", False)
    )
    return {"is_mock": is_mock, "supports_logprobs": supports_logprobs}


class ProviderManager:
    """Holds loaded providers and reuses them across experiments."""

    def __init__(self) -> None:
        self._instances: dict[str, LLMProvider] = {}
        self._lock = threading.Lock()

    def get(self, name: str, definition: dict | None = None) -> LLMProvider:
        with self._lock:
            provider = self._instances.get(name)
            if provider is None:
                provider = create_provider(name, definition)
                self._instances[name] = provider
            return provider

    def load(self, name: str, definition: dict | None = None) -> LLMProvider:
        provider = self.get(name, definition)
        if not provider.loaded:
            provider.load()
        return provider

    def unload(self, name: str) -> None:
        with self._lock:
            provider = self._instances.pop(name, None)
        if provider is not None:
            try:
                provider.unload()
            except Exception:
                pass

    def loaded_names(self) -> list[str]:
        with self._lock:
            return [p.name for p in self._instances.values() if p.loaded]

    def status(self, name: str) -> dict:
        try:
            provider = self.get(name)
            return provider.describe()
        except ProviderError as exc:
            return {"name": name, "loaded": False, "load_error": exc.message, "supports_logprobs": False, "is_mock": False}

    def unload_all(self) -> None:
        for name in list(self._instances):
            self.unload(name)


manager = ProviderManager()
