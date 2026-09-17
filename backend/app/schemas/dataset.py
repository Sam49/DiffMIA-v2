from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DatasetOut(ORMModel):
    id: int
    name: str
    description: str
    source_format: str
    content_hash: str
    item_count: int
    created_at: object | None = None


class DatasetItemOut(ORMModel):
    id: int
    dataset_id: int
    external_id: str
    dataset_name: str
    problem_statement: str
    code: str
    language: str
    metadata_json: str
    content_hash: str
    position: int
    created_at: object | None = None


class ManualItem(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    problem_statement: str = Field(default="", max_length=50_000)
    code: str = Field(min_length=1, max_length=500_000)
    language: str = Field(default="python", pattern=r"^[a-z0-9_+#.-]+$")
    metadata: dict = Field(default_factory=dict)


class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    items: list[ManualItem] = Field(min_length=1, max_length=10_000)


class DatasetUploadResponse(BaseModel):
    dataset_id: int
    name: str
    items_added: int
    items_skipped: int
    source_format: str
    content_hash: str
