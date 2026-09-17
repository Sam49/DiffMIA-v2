"""In-process background worker.

A single worker thread consumes a FIFO queue of experiment ids, so GPU /
local-model workloads are serialized without blocking HTTP requests. Queue
size is exposed through ``/metrics``. For larger deployments use the Celery
worker (workers/tasks.py) with ``WORKER_MODE=celery``.
"""
from __future__ import annotations

import logging
import queue
import threading

from app.core.exceptions import NotFoundError
from app.db.session import get_session_factory
from app.services.experiment_service import get_experiment, mark_failed
from app.workers.run_pipeline import run_experiment

logger = logging.getLogger("diffmia.worker")


class ExperimentExecutor:
    def __init__(self) -> None:
        self._queue: queue.Queue[int] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._active: set[int] = set()

    # ── lifecycle ────────────────────────────────────────────────
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = threading.Thread(target=self._run_loop, name="diffmia-worker", daemon=True)
            self._thread.start()
            logger.info("Experiment worker started (thread mode).")

    def stop(self) -> None:
        with self._lock:
            self._started = False
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ── API ──────────────────────────────────────────────────────
    def submit(self, experiment_id: int) -> None:
        self._queue.put(experiment_id)

    def dispatch(self, experiment_id: int) -> None:
        """Route the job to the in-process worker or the Celery worker.

        WORKER_MODE=celery requires the optional celery dependencies and the
        ``celery -A app.workers.tasks:celery_app worker`` process (see
        docker-compose worker service). Falls back to the thread worker.
        """
        from app.core.config import get_settings

        if get_settings().worker_mode == "celery":
            try:
                if self._try_send_celery(experiment_id):
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Celery dispatch unavailable (%s); using thread worker", exc)
        # Fall back to the in-process worker. start() is idempotent, so this
        # is safe even when WORKER_MODE=celery (main.py does not start the
        # thread loop in that case and a broker outage must not stall jobs).
        self.start()
        self.submit(experiment_id)

    @staticmethod
    def _try_send_celery(experiment_id: int) -> bool:
        """Publish the job to Celery with a short-lived, zero-retry connection.

        Celery's own producer would otherwise run a ~20-retry reconnect loop
        against an unreachable broker, stalling dispatch for minutes. Opening
        an explicit kombu connection (max_retries=0, tight timeout) makes a
        broker outage fail in about a second so the thread worker can take over.
        """
        from kombu import Connection  # type: ignore[import-not-found]

        from app.core.config import get_settings
        from app.workers.tasks import celery_app

        if celery_app is None:
            return False
        settings = get_settings()
        connection = Connection(
            settings.celery_broker_url,
            transport_options={"max_retries": 0},
            connect_timeout=2.0,
        )
        try:
            connection.ensure_connection(max_retries=0, timeout=2.0)
            celery_app.send_task(
                "diffmia.run_experiment", args=[experiment_id], connection=connection
            )
            return True
        except Exception:
            return False
        finally:
            connection.release()

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def queue_size(self) -> int:
        return self._queue.qsize()

    # ── internals ────────────────────────────────────────────────
    def _run_loop(self) -> None:
        while True:
            with self._lock:
                if not self._started:
                    return
            try:
                experiment_id = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            with self._lock:
                self._active.add(experiment_id)
            try:
                self._run_safely(experiment_id)
            finally:
                with self._lock:
                    self._active.discard(experiment_id)
                self._queue.task_done()

    def _run_safely(self, experiment_id: int) -> None:
        # The enqueuing request may not have committed yet — wait briefly for the
        # row to become visible before treating the job as orphaned.
        import time

        session_factory = get_session_factory()
        session = session_factory()
        try:
            experiment = None
            for _ in range(20):
                try:
                    experiment = get_experiment(session, experiment_id)
                    break
                except NotFoundError:
                    session.rollback()
                    time.sleep(0.25)
            if experiment is None:
                logger.warning("Experiment %s not found; dropping queued job", experiment_id)
                return
            # Skip jobs cancelled before they started.
            if experiment.status == "CANCELLED":
                session.commit()
                return
        finally:
            session.close()
        try:
            result = run_experiment(experiment_id)
            logger.info("Experiment %s finished: %s", experiment_id, result.get("status"))
        except Exception as exc:  # defensive: run_experiment already handles most errors
            logger.exception("Experiment %s crashed in executor", experiment_id)
            session_factory2 = get_session_factory()
            session = session_factory2()
            try:
                mark_failed(session, experiment_id, error_code="EXPERIMENT_INTERNAL_ERROR",
                            error_message=str(exc))
                session.commit()
            finally:
                session.close()


executor = ExperimentExecutor()
