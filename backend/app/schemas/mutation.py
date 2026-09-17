from __future__ import annotations

from app.schemas.common import ORMModel


class MutationOut(ORMModel):
    id: int
    experiment_id: int
    snippet_id: int
    mutation_index: int
    seed: int
    original_code: str
    mutated_code: str
    language: str
    mapping_json: str
    validation_status: str
    validation_score: float
    created_at: object | None = None
