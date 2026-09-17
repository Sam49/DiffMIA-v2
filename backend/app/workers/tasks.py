"""Optional Celery worker for larger deployments.

Enable with ``WORKER_MODE=celery`` and run:

    celery -A app.workers.tasks:celery_app worker --loglevel=info

The task executes the same synchronous pipeline as the thread worker.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("diffmia.worker.celery")


def _make_celery():
    from celery import Celery  # type: ignore[import-not-found]

    from app.core.config import get_settings

    settings = get_settings()
    app = Celery(
        "diffmia",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json")

    @app.task(name="diffmia.run_experiment", bind=True, max_retries=0)
    def run_experiment_task(self, experiment_id: int) -> dict:  # noqa: ARG001
        from app.workers.run_pipeline import run_experiment

        return run_experiment(experiment_id)

    return app


try:
    celery_app = _make_celery()
except ImportError:  # celery not installed -> harmless in thread mode
    celery_app = None  # type: ignore[assignment]
