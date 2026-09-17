from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    message: str


class ErrorOut(BaseModel):
    error: str
    message: str
    request_id: str = ""


class Page(BaseModel):
    total: int
    limit: int
    offset: int
