"""email verification + password reset columns on users

Revision ID: c4d8e1f9a2b3
Revises: a7f3c9d2e5b1
Create Date: 2026-09-11 12:00:00.000000+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d8e1f9a2b3"
down_revision = "a7f3c9d2e5b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_token_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_users_email_verified"), "users", ["email_verified"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email_verified"), table_name="users")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_token_hash")
    op.drop_column("users", "email_verified")
