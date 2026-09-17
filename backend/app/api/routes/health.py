from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.core.context import request_id_var
from app.db.session import get_db
from app.services import metrics_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.app_env,
        "database": database,
        "worker": settings.worker_mode,
        "request_id": request_id_var.get() or "",
    }


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    return metrics_service.snapshot(db)
