from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ModelOut(ORMModel):
    id: int
    name: str
    display_name: str
    provider: str
    model_id: str
    description: str
    config_json: str = "{}"
    is_active: bool


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(default="", max_length=255)
    provider: str = Field(pattern=r"^(mock|transformers|openai_compatible)$")
    model_id: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=5000)
    config_json: str = "{}"


class ModelStatusOut(BaseModel):
    id: int
    name: str
    display_name: str
    provider: str
    supports_logprobs: bool
    is_mock: bool
    loaded: bool
    device: str = ""
    load_error: str = ""
    health: str = "unknown"
