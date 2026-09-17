"""Personalized TARS agent settings per user (mode, tools, oauth)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, EncryptedString, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.auth.models import User


class TARSSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Personalized TARS agent settings per user (mode, tools, oauth)."""

    __tablename__ = "tars_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(
        String(32), default="attend", nullable=False
    )  # "attend" | "task"

    # Tool preferences and Google OAuth account linking
    disabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    google_refresh_token: Mapped[str | None] = mapped_column(EncryptedString(512), nullable=True)
    google_access_token: Mapped[str | None] = mapped_column(EncryptedString(1024), nullable=True)
    google_linked_email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    google_client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    google_client_secret: Mapped[str | None] = mapped_column(EncryptedString(256), nullable=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="settings")

    @property
    def google_linked(self) -> bool:
        return bool(self.google_refresh_token or self.google_access_token)

    @google_linked.setter
    def google_linked(self, value: bool) -> None:
        if not value:
            self.google_refresh_token = None
            self.google_access_token = None
            self.google_linked_email = None

    @property
    def google_account_email(self) -> str | None:
        return self.google_linked_email

    @google_account_email.setter
    def google_account_email(self, value: str | None) -> None:
        self.google_linked_email = value

    def __repr__(self) -> str:
        return f"<TARSSettings user_id={self.user_id!r} mode={self.mode!r}>"


__all__ = ["TARSSettings"]
