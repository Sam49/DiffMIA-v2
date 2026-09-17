"""Structured JSON logging.

Log records carry: timestamp, level, logger, message, plus context fields
(request_id, experiment_id, user, ...) that are merged in automatically.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from app.core import context


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)
        # Context fields for correlation
        if context.request_id_var.get():
            payload["request_id"] = context.request_id_var.get()
        if context.experiment_id_var.get():
            payload["experiment_id"] = context.experiment_id_var.get()
        if context.user_var.get():
            payload["user"] = context.user_var.get()
        # Arbitrary extra fields attached via extra={"fields": {...}}
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key not in payload:
                    payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Quiet noisy third-party loggers in dev/demo
    for noisy in ("uvicorn.access", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
