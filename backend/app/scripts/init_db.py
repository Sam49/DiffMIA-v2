"""Initialize the database and seed defaults.

Usage: python -m app.scripts.init_db

With AUTO_CREATE_TABLES=true this runs table creation directly (SQLite and
PostgreSQL both supported). When DATABASE_URL points to PostgreSQL in
production you can instead run `alembic upgrade head` first; the script is
idempotent either way.
"""
from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scripts.seed import initialize_database, seed_defaults


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_database()
    seed_defaults()
    print(f"DiffMIA database ready at {settings.database_url.split('@')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
