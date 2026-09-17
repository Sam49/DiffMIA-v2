from __future__ import annotations

from pydantic import BaseModel


class ReportOut(BaseModel):
    experiment_id: int
    format: str
    filename: str
    size_bytes: int
    content_type: str
