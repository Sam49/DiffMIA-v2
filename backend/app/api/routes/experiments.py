from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.exceptions import ValidationError
from app.db.session import get_db
from app.models import User
from app.models.enums import ExperimentStatus, UserRole
from app.schemas.common import MessageOut, ORMModel
from app.schemas.experiment import ExperimentCreate, ExperimentDetail, ExperimentOut
from app.schemas.mutation import MutationOut
from app.schemas.report import ReportOut
from app.services import dataset_service, experiment_service, report_service, results_service
from app.workers.executor import executor

router = APIRouter(tags=["experiments"])


def _detail(db: Session, experiment_id: int) -> dict:
    return results_service.build_results(db, experiment_id)["experiment"]


@router.get("/experiments")
def list_experiments(
    status: str | None = Query(default=None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows, total = experiment_service.list_experiments(db, offset=offset, limit=limit)
    items = []
    for row in rows:
        data = ExperimentOut.model_validate(row).model_dump(mode="json")
        data["model_name"] = row.model.display_name if row.model else ""
        data["dataset_name"] = row.dataset.name if row.dataset else ""
        items.append(data)
    if status:
        items = [i for i in items if i["status"] == status.upper()]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/experiments", response_model=ExperimentDetail, status_code=201)
def create_experiment(
    payload: ExperimentCreate,
    user: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> dict:
    experiment = experiment_service.create_experiment(db, user, payload)
    return _detail(db, experiment.id)


@router.get("/experiments/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return _detail(db, experiment_id)


@router.post("/experiments/{experiment_id}/run", response_model=ExperimentDetail)
def run_experiment(
    experiment_id: int,
    _: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> dict:
    experiment = experiment_service.get_experiment(db, experiment_id)
    if experiment.status == ExperimentStatus.RUNNING.value:
        raise ValidationError("Experiment is already running.", code="INVALID_STATE")
    if experiment.status == ExperimentStatus.CANCELLED.value:
        # allow a fresh rerun after cancellation
        experiment.status = ExperimentStatus.QUEUED.value
        experiment.error_code = ""
        experiment.error_message = ""
    experiment.progress_message = "Queued…"
    executor.dispatch(experiment_id)
    return _detail(db, experiment_id)


@router.post("/experiments/{experiment_id}/cancel", response_model=ExperimentDetail)
def cancel_experiment(
    experiment_id: int,
    _: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> dict:
    experiment_service.cancel_experiment(db, experiment_id)
    return _detail(db, experiment_id)


@router.get("/experiments/{experiment_id}/results")
def experiment_results(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return results_service.build_results(db, experiment_id)


@router.get("/experiments/{experiment_id}/mutations")
def experiment_mutations(
    experiment_id: int,
    snippet_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy import select

    from app.models import Mutation

    query = select(Mutation).where(Mutation.experiment_id == experiment_id).order_by(Mutation.snippet_id, Mutation.mutation_index)
    if snippet_id is not None:
        query = query.where(Mutation.snippet_id == snippet_id)
    rows = db.execute(query).scalars().all()
    return {"items": [MutationOut.model_validate(r).model_dump(mode="json") for r in rows],
            "total": len(rows)}


@router.get("/experiments/{experiment_id}/logs")
def experiment_logs(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy import select

    from app.models import ExperimentLog

    rows = db.execute(
        select(ExperimentLog).where(ExperimentLog.experiment_id == experiment_id)
        .order_by(ExperimentLog.created_at.desc()).limit(200)
    ).scalars().all()
    return {"items": [
        {"id": r.id, "level": r.level, "message": r.message, "context_json": r.context_json,
         "created_at": r.created_at}
        for r in rows
    ]}


# ── Export endpoints ─────────────────────────────────────────────
def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/experiments/{experiment_id}/export/json")
def export_json(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    content = report_service.export_json(db, experiment_id).encode("utf-8")
    return _download(content, f"experiment-{experiment_id}.json", "application/json")


@router.get("/experiments/{experiment_id}/export/csv")
def export_csv(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    content = report_service.export_csv(db, experiment_id).encode("utf-8")
    return _download(content, f"experiment-{experiment_id}.csv", "text/csv")


@router.get("/experiments/{experiment_id}/export/markdown")
def export_markdown(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    content = report_service.export_markdown(db, experiment_id).encode("utf-8")
    return _download(content, f"experiment-{experiment_id}.md", "text/markdown")


@router.get("/experiments/{experiment_id}/export/pdf", response_model=ReportOut)
def export_pdf(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    experiment_service.get_experiment(db, experiment_id)
    try:
        content = report_service.export_pdf(db, experiment_id)
    except ImportError as exc:  # reportlab not installed
        raise ValidationError(
            "PDF export requires 'reportlab'. Install backend requirements.", code="DEPENDENCY_MISSING"
        ) from exc
    return _download(content, f"experiment-{experiment_id}.pdf", "application/pdf")
