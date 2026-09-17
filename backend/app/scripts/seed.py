from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import create_all, session_scope
from app.models import Dataset, User
from app.models.enums import UserRole
from app.services import dataset_service
from app.services.dataset_parsers import parse_dataset_content
from app.services.model_service import seed_models_from_config

logger = logging.getLogger("diffmia.seed")

#: Extensions the dataset parsers can ingest from the bundled datasets folder.
DATASET_SUFFIXES = {".json", ".jsonl", ".ndjson", ".csv", ".py"}


def initialize_database() -> None:
    """Create tables when Alembic migrations were not run (local dev / demo)."""
    create_all()
    logger.info("Database tables ensured (auto_create_tables=true).")


def seed_defaults() -> None:
    settings = get_settings()
    with session_scope() as session:
        seed_models_from_config(session)
        user_count = session.execute(select(func.count()).select_from(User)).scalar_one()
        if user_count == 0:
            session.add(
                User(
                    username=settings.admin_username,
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    role=UserRole.ADMIN.value,
                )
            )
            logger.info("Seeded default admin user '%s'.", settings.admin_username)
            if settings.admin_password == "admin":
                logger.warning(
                    "Default admin password is in use. Set ADMIN_PASSWORD before deploying."
                )
        session.commit()


def _bundled_dataset_name(records: list[dict], fallback: str) -> str:
    """Use the dataset's own name when every record agrees on one."""
    names = {str(r.get("dataset_name") or "").strip() for r in records}
    names.discard("")
    if len(names) == 1:
        return names.pop()
    return fallback


def seed_bundled_datasets() -> int:
    """Import every supported file in ``BUNDLED_DATASETS_DIR`` into the database.

    Idempotent: a dataset whose parsed content hash already exists is skipped, so
    booting repeatedly never duplicates rows and a re-seeded database always
    lists the datasets the project ships with. Returns the number imported.
    """
    settings = get_settings()
    directory = Path(settings.bundled_datasets_dir)
    if not directory.is_dir():
        logger.debug("Bundled datasets directory %s does not exist; skipping.", directory)
        return 0

    imported = 0
    failures: list[str] = []
    with session_scope() as session:
        existing = {
            digest
            for (digest,) in session.execute(select(Dataset.content_hash)).all()
        }
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in DATASET_SUFFIXES:
                continue
            try:
                content = path.read_text(encoding="utf-8")
                source_format = path.suffix.lower().lstrip(".")
                records, _ = parse_dataset_content(
                    content, source_format=source_format, default_dataset=path.stem
                )
                digest = dataset_service.records_hash(records)
                if digest in existing:
                    continue
                dataset, skipped = dataset_service.create_dataset(
                    session,
                    name=_bundled_dataset_name(records, path.stem),
                    records=records,
                    description=f"Bundled benchmark dataset imported from datasets/{path.name}.",
                    source_format=source_format,
                )
                existing.add(digest)
                imported += 1
                logger.info(
                    "Imported bundled dataset '%s' (%s items, %s skipped) from %s.",
                    dataset.name,
                    dataset.item_count,
                    skipped,
                    path.name,
                )
            except Exception as exc:  # noqa: BLE001 - one bad file must not block boot
                failures.append(f"{path.name}: {exc}")
                logger.warning("Bundled dataset %s could not be imported: %s", path.name, exc)
        session.commit()

    if failures:
        logger.warning("Skipped %s bundled dataset file(s) with errors.", len(failures))
    return imported
