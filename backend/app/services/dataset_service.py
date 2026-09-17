from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Dataset, DatasetItem
from app.services.dataset_parsers import parse_dataset_content


def records_hash(records: list[dict]) -> str:
    canonical = json.dumps(records, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_content_hash = records_hash  # backward-compatible alias


def create_dataset(
    db: Session,
    *,
    name: str,
    records: list[dict],
    description: str = "",
    source_format: str = "jsonl",
    user_id: int | None = None,
) -> tuple[Dataset, int]:
    """Persist records into a new dataset. Returns (dataset, skipped_count)."""
    if not name.strip():
        raise ValidationError("Dataset name is required.")
    seen: set[str] = set()
    deduped: list[dict] = []
    skipped = 0
    for record in records:
        key = record["external_id"]
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        deduped.append(record)

    if not deduped:
        raise ValidationError("Every item in the dataset is a duplicate; nothing to import.")

    dataset = Dataset(
        name=name.strip(),
        description=description,
        source_format=source_format,
        content_hash=_content_hash(deduped),
        item_count=len(deduped),
        created_by=user_id,
    )
    db.add(dataset)
    db.flush()  # assign dataset.id

    for position, record in enumerate(deduped):
        item_hash = hashlib.sha256(record["code"].encode("utf-8")).hexdigest()
        db.add(
            DatasetItem(
                dataset_id=dataset.id,
                external_id=record["external_id"],
                dataset_name=record.get("dataset_name") or dataset.name,
                problem_statement=record.get("problem_statement") or "",
                code=record["code"],
                language=record.get("language") or "python",
                metadata_json=json.dumps(record.get("metadata") or {}, ensure_ascii=True),
                content_hash=item_hash,
                position=position,
            )
        )
    db.flush()
    return dataset, skipped


def parse_and_store_text(
    db: Session,
    *,
    content: str,
    name: str,
    description: str = "",
    source_format: str = "jsonl",
    user_id: int | None = None,
) -> tuple[Dataset, int]:
    records, skipped = parse_dataset_content(content, source_format=source_format, default_dataset=name)
    dataset, duplicate_skips = create_dataset(db, name=name, records=records, description=description,
                                              source_format=source_format, user_id=user_id)
    return dataset, skipped + duplicate_skips


def get_dataset(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} does not exist.")
    return dataset


def get_item(db: Session, item_id: int) -> DatasetItem:
    item = db.get(DatasetItem, item_id)
    if item is None:
        raise NotFoundError(f"Snippet {item_id} does not exist.")
    return item


def list_datasets(db: Session, *, offset: int = 0, limit: int = 50) -> tuple[list[Dataset], int]:
    total = db.execute(select(func.count()).select_from(Dataset)).scalar_one()
    rows = db.execute(
        select(Dataset).order_by(Dataset.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return list(rows), int(total)


def list_items(
    db: Session, dataset_id: int, *, offset: int = 0, limit: int = 200
) -> tuple[list[DatasetItem], int]:
    total = db.execute(
        select(func.count()).select_from(DatasetItem).where(DatasetItem.dataset_id == dataset_id)
    ).scalar_one()
    rows = db.execute(
        select(DatasetItem)
        .where(DatasetItem.dataset_id == dataset_id)
        .order_by(DatasetItem.position)
        .offset(offset)
        .limit(limit)
    ).scalars().all()
    return list(rows), int(total)


def delete_dataset(db: Session, dataset_id: int) -> None:
    dataset = get_dataset(db, dataset_id)
    db.delete(dataset)
