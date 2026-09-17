from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole
from app.schemas.common import MessageOut, ORMModel
from app.schemas.dataset import DatasetCreateRequest, DatasetItemOut, DatasetOut, DatasetUploadResponse
from app.services import dataset_service

router = APIRouter(tags=["datasets"])


@router.get("/datasets")
def list_datasets(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows, total = dataset_service.list_datasets(db, offset=offset, limit=limit)
    return {
        "items": [DatasetOut.model_validate(d).model_dump(mode="json") for d in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    return DatasetOut.model_validate(dataset)


@router.get("/datasets/{dataset_id}/items")
def list_dataset_items(
    dataset_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    dataset_service.get_dataset(db, dataset_id)
    rows, total = dataset_service.list_items(db, dataset_id, offset=offset, limit=limit)
    return {
        "items": [DatasetItemOut.model_validate(r).model_dump(mode="json") for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/datasets/{dataset_id}/export")
def export_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    dataset = dataset_service.get_dataset(db, dataset_id)
    rows, _ = dataset_service.list_items(db, dataset_id, offset=0, limit=10_000)
    lines = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        lines.append(
            json.dumps(
                {
                    "id": row.external_id,
                    "dataset_name": row.dataset_name,
                    "problem_statement": row.problem_statement,
                    "code": row.code,
                    "language": row.language,
                    "metadata": metadata,
                },
                ensure_ascii=True,
            )
        )
    payload = "\n".join(lines)
    return Response(
        content=payload,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="dataset-{dataset_id}.jsonl"'},
    )


@router.post("/datasets", response_model=DatasetUploadResponse, status_code=201)
def create_dataset(
    payload: DatasetCreateRequest,
    user: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> DatasetUploadResponse:
    records = [
        {
            "external_id": item.external_id or f"item_{idx}",
            "dataset_name": payload.name,
            "problem_statement": item.problem_statement,
            "code": item.code,
            "language": item.language,
            "metadata": item.metadata,
        }
        for idx, item in enumerate(payload.items)
    ]
    dataset, skipped = dataset_service.create_dataset(
        db, name=payload.name, records=records, description=payload.description,
        source_format="manual", user_id=user.id,
    )
    return DatasetUploadResponse(
        dataset_id=dataset.id, name=dataset.name, items_added=dataset.item_count,
        items_skipped=skipped, source_format="manual", content_hash=dataset.content_hash,
    )


@router.post("/datasets/upload", response_model=DatasetUploadResponse, status_code=201)
def upload_dataset(
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    user: User = Depends(require_roles(UserRole.RESEARCHER.value)),
    db: Session = Depends(get_db),
) -> DatasetUploadResponse:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = file.file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise ValidationError(
                f"Upload exceeds the {get_settings().max_upload_mb} MB limit.",
                code="FILE_TOO_LARGE",
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError("File is not valid UTF-8 text.", code="INVALID_ENCODING")

    filename = file.filename or "dataset.txt"
    source_format = filename.rsplit(".", 1)[-1] if "." in filename else "jsonl"
    if source_format not in ("json", "jsonl", "ndjson", "csv", "py", "python", "txt"):
        raise ValidationError(
            f"Unsupported file type '.{source_format}'. Supported: .json, .jsonl, .csv, .py.",
            code="UNSUPPORTED_FORMAT",
        )
    dataset_name = (name or filename.rsplit(".", 1)[0]).strip() or "uploaded_dataset"
    dataset, skipped = dataset_service.parse_and_store_text(
        db, content=content, name=dataset_name, description=description,
        source_format=source_format, user_id=user.id,
    )
    return DatasetUploadResponse(
        dataset_id=dataset.id, name=dataset.name, items_added=dataset.item_count,
        items_skipped=skipped, source_format=source_format, content_hash=dataset.content_hash,
    )


@router.delete("/datasets/{dataset_id}", response_model=MessageOut)
def delete_dataset(
    dataset_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN.value)),
    db: Session = Depends(get_db),
) -> MessageOut:
    dataset_service.delete_dataset(db, dataset_id)
    return MessageOut(message=f"Dataset {dataset_id} deleted.")
