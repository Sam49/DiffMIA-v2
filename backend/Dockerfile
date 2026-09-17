# DiffMIA backend (FastAPI).
# Build from the repository root so PROJECT_ROOT paths resolve correctly:
#   docker build -f backend/Dockerfile -t diffmia-backend .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Install runtime dependencies first for Docker layer caching.
COPY backend/requirements.txt backend/requirements.txt
COPY backend/requirements-celery.txt backend/requirements-celery.txt
RUN pip install --no-cache-dir \
    -r backend/requirements.txt \
    -r backend/requirements-celery.txt

# Whole repository → /app so backend/app, configs/, datasets/, database/
# and alembic.ini land where app.core.config.PROJECT_ROOT expects them.
COPY . /app/
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status==200 else 1)"

# Entrypoint: apply migrations (PostgreSQL / RUN_MIGRATIONS=true) or
# auto-create tables (SQLite quick start), then seed, then serve.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-false}\" = \"true\" ] || printf '%s' \"$DATABASE_URL\" | grep -q '^postgresql'; then alembic upgrade head; else python -m app.scripts.init_db; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
