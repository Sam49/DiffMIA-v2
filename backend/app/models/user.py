from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    # One account per Google identity. The index is partial because every local
    # account legitimately carries an empty google_sub; a plain UNIQUE would
    # reject the second local account. Without this, two rows could share a
    # subject and the provisioning lookup would be ambiguous.
    __table_args__ = (
        Index(
            "ix_users_google_sub_unique",
            "google_sub",
            unique=True,
            sqlite_where=text("google_sub != ''"),
            postgresql_where=text("google_sub != ''"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="local", server_default="local", index=True)
    google_sub: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="VIEWER", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Self-registration: accounts must confirm their address before signing in.
    # OAuth-provisioned accounts are pre-verified (Google already validated the
    # address); admins seeded at first boot are trusted.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=func.true(), index=True
    )
    # Password reset: HMAC-signed, single-use, time-limited token (no DB row).
    # The hash is stored so a DB leak cannot be replayed against the endpoint.
    password_reset_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def google_linked(self) -> bool:
        """Whether a Google identity is attached (the raw subject is never serialized)."""
        return bool(self.google_sub)
