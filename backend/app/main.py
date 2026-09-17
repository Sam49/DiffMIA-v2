"""FastAPI application entry point.

Error responses are always structured:

    {"error": "CODE", "message": "...", "request_id": "..."}

Raw tracebacks are never returned to clients.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import api_router
from app.core import context
from app.core.config import get_settings
from app.core.exceptions import DiffMiaError
from app.core.logging import configure_logging
from app.core.ratelimit import SlidingWindowLimiter
from app.inference.registry import manager as provider_manager
from app.scripts.seed import initialize_database, seed_bundled_datasets, seed_defaults
from app.workers.executor import executor

logger = logging.getLogger("diffmia")

_SKIP_RATE_LIMIT = {"/api/health", "/health", "/api/metrics", "/metrics", "/api/demo/status"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.auto_create_tables:
        initialize_database()
    seed_defaults()
    if settings.seed_bundled_datasets:
        seed_bundled_datasets()
    if settings.worker_mode == "celery":
        logger.info("Worker mode is 'celery' — run `celery -A app.workers.tasks:celery_app worker` separately.")
    else:
        executor.start()
    yield
    executor.stop()
    provider_manager.unload_all()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=f"{settings.app_name} API",
        description=(
            "Detect LLM benchmark contamination through differential loss analysis. "
            "Compares model likelihood on original benchmark code vs semantically "
            "equivalent identifier-mutated variants."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = context.new_request_id()
        context.set_request_context(request_id)
        token = context.request_id_var.set(request_id)
        from app.services import metrics_service

        metrics_service.record_request(request.url.path)
        limiter = request.app.state.rate_limiter
        if request.url.path not in _SKIP_RATE_LIMIT:
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(f"{client}:{request.url.path}"):
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": "RATE_LIMITED",
                        "message": "Too many requests. Slow down and try again.",
                        "request_id": request_id,
                    },
                )
                response.headers["X-Request-ID"] = request_id
                context.request_id_var.reset(token)
                return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        context.request_id_var.reset(token)
        return response

    # Structured error handlers
    @app.exception_handler(DiffMiaError)
    async def diffmia_error_handler(request: Request, exc: DiffMiaError):
        logger.warning("%s %s -> %s", request.method, request.url.path, exc.code)
        body = {"error": exc.code, "message": exc.message, "request_id": context.request_id_var.get() or ""}
        if exc.details is not None:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Pydantic v2 error entries may embed the original exception object in
        # their context (e.g. validators raising ValueError), which is not
        # JSON-serializable — sanitize to primitives.
        def _json_safe(errors: list[dict]) -> list[dict]:
            safe: list[dict] = []
            for err in errors[:20]:
                cleaned: dict = {}
                for key, value in err.items():
                    if key == "ctx" and isinstance(value, dict):
                        cleaned[key] = {k: str(v) for k, v in value.items()}
                    else:
                        cleaned[key] = value
                safe.append(cleaned)
            return safe

        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "request_id": context.request_id_var.get() or "",
                "details": _json_safe(exc.errors()),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTP_ERROR",
                "message": str(exc.detail),
                "request_id": context.request_id_var.get() or "",
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected internal error occurred.",
                "request_id": context.request_id_var.get() or "",
            },
        )

    app.state.rate_limiter = SlidingWindowLimiter(max_requests=max(settings.rate_limit_per_minute, 1))
    app.include_router(api_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "demo": "/api/demo/status",
            "message": "Detecting LLM benchmark contamination through differential loss analysis.",
        }

    return app


app = create_app()
