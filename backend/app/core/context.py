"""Context variables used for request correlation and structured logging."""
from __future__ import annotations

import contextvars
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
experiment_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("experiment_id", default="")
user_var: contextvars.ContextVar[str] = contextvars.ContextVar("user", default="")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_context(request_id: str) -> None:
    request_id_var.set(request_id)


def set_experiment_context(experiment_id: int | str) -> None:
    experiment_id_var.set(str(experiment_id))
