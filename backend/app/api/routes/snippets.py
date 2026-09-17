from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import DatasetItem, Experiment, Mutation, User
from app.schemas.dataset import DatasetItemOut
from app.schemas.mutation import MutationOut

router = APIRouter(tags=["snippets"])


@router.get("/snippets/{snippet_id}", response_model=DatasetItemOut)
def get_snippet(
    snippet_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.services.dataset_service import get_item

    return DatasetItemOut.model_validate(get_item(db, snippet_id))


@router.get("/snippets/{snippet_id}/mutations")
def snippet_mutations(
    snippet_id: int,
    experiment_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from app.services.dataset_service import get_item

    item = get_item(db, snippet_id)
    if experiment_id is None:
        experiment_id = db.execute(
            select(Experiment.id)
            .where(Experiment.dataset_id == item.dataset_id, Experiment.status == "COMPLETED")
            .order_by(Experiment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if experiment_id is None:
        return {"items": [], "total": 0, "experiment_id": None}
    rows = db.execute(
        select(Mutation)
        .where(Mutation.experiment_id == experiment_id, Mutation.snippet_id == snippet_id)
        .order_by(Mutation.mutation_index)
    ).scalars().all()
    return {
        "items": [MutationOut.model_validate(r).model_dump(mode="json") for r in rows],
        "total": len(rows),
        "experiment_id": experiment_id,
    }
