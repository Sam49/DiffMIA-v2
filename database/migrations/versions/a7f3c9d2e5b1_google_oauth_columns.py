"""google oauth columns on users

Revision ID: a7f3c9d2e5b1
Revises: 3496a5be1cb2
Create Date: 2026-09-09 12:00:00.000000+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7f3c9d2e5b1"
down_revision = "3496a5be1cb2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(length=32), nullable=False, server_default="local"),
    )
    op.add_column(
        "users",
        sa.Column("google_sub", sa.String(length=64), nullable=False, server_default=""),
    )
    op.create_index(op.f("ix_users_auth_provider"), "users", ["auth_provider"], unique=False)
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_index(op.f("ix_users_auth_provider"), table_name="users")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "auth_provider")
