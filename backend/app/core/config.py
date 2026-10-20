"""Application configuration.

All configuration is driven by environment variables (optionally loaded from a
`.env` file at the repository root). Secrets are never hard-coded here — they
must be provided through the environment.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # repository root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "DiffMIA"
    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-to-a-long-random-string"
    access_token_expire_minutes: int = 1440

    # Database
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'diffmia.db').as_posix()}"
    auto_create_tables: bool = True

    # Redis (optional)
    redis_url: str = ""

    # CORS (comma separated)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Default admin user (seeded on first boot)
    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_email: str = "admin@diffmia.local"

    # Demo mode
    demo_model_provider: str = "mock"
    demo_model_id: str = "diffmia-mock"  # key in configs/models.yaml
    demo_dataset_path: str = str(PROJECT_ROOT / "datasets" / "sample.jsonl")

    # Bundled benchmark datasets (every supported file in this folder is imported
    # into the database on boot, so the Datasets page always lists what the
    # project ships with). Re-imports are skipped by content hash.
    bundled_datasets_dir: str = str(PROJECT_ROOT / "datasets")
    seed_bundled_datasets: bool = True

    # Models registry
    models_config_path: str = str(PROJECT_ROOT / "configs" / "models.yaml")

    # Inference defaults
    model_cache_dir: str = str(PROJECT_ROOT / "data" / "models")
    hf_token: str = ""
    device: str = "auto"
    torch_dtype: str = "auto"

    # Google OAuth SSO (optional — set both to enable "Continue with Google")
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_frontend_origin: str = "http://localhost:5173"
    oauth_redirect_uri: str = ""  # derived from the request base URL when empty
    oauth_default_role: str = "VIEWER"

    # API model credentials (never log these)
    deepseek_endpoint: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-coder"
    openai_endpoint: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = ""

    # Pipeline defaults
    default_mutation_count: int = 5
    default_mutation_seed: int = 42
    default_mutation_strength: float = 0.3
    default_batch_size: int = 4
    default_max_tokens: int = 4096
    default_temperature: float = 0.0
    enable_token_loss_storage: bool = False
    enable_inference_cache: bool = True
    request_timeout_seconds: int = 300
    api_retry_attempts: int = 3

    # Worker
    worker_mode: str = "thread"  # thread | celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # Registration (optional — disabled by default; enable for open sign-ups)
    registration_enabled: bool = False
    registration_default_role: str = "VIEWER"

    # Email verification (for self-registered accounts) and password reset.
    # With no SMTP host configured, emails are logged and — in non-production
    # environments — also surfaced in the API response for developer testing.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = "diffmia@localhost"
    email_verification_token_ttl_minutes: int = 60 * 24
    email_verification_required: bool = True
    password_reset_token_ttl_minutes: int = 60
    public_url: str = "http://localhost:5173"

    # Automatic sign-in (no login page). When enabled, the frontend establishes
    # a session for AUTO_LOGIN_USERNAME at startup, so the UI never presents a
    # sign-in screen. Off by default — enable it only for trusted/self-hosted
    # installations, never for a publicly reachable instance.
    auto_login_enabled: bool = False
    auto_login_username: str = "admin"

    # Security / limits
    max_upload_mb: int = 25
    rate_limit_per_minute: int = 600
    login_rate_limit_per_minute: int = 20

    @field_validator(
        "demo_dataset_path",
        "bundled_datasets_dir",
        "models_config_path",
        "model_cache_dir",
        mode="after",
    )
    @classmethod
    def _resolve_relative_paths(cls, value: str) -> str:
        """Interpret relative paths in .env/compose relative to the repo root."""
        candidate = Path(value)
        if not candidate.is_absolute():
            return str((PROJECT_ROOT / candidate).resolve())
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def database_path(self) -> Path | None:
        """Filesystem path for file-based SQLite databases."""
        if not self.is_sqlite:
            return None
        raw = self.database_url.replace("sqlite:///", "", 1)
        if raw in (":memory:", ""):
            return None
        return Path(raw).expanduser()


@lru_cache
def get_settings() -> Settings:
    # Make sure local data directories exist early.
    settings = Settings()
    if settings.is_sqlite:
        db_path = settings.database_path
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
    Path(settings.model_cache_dir).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", settings.model_cache_dir)
    os.environ.setdefault("TRANSFORMERS_CACHE", settings.model_cache_dir)
    os.environ.setdefault("HF_HUB_CACHE", settings.model_cache_dir)
    return settings
