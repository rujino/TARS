"""Personalized TARS agent settings per user (humor, honesty, mode)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, EncryptedString, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.auth.models import User


class TARSSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Personalized TARS agent settings per user (humor, honesty, mode)."""

    __tablename__ = "tars_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    humor_level: Mapped[float] = mapped_column(
        Float, default=0.90, nullable=False
    )  # 0.0 to 1.0 (Default: 90%)
    honesty_level: Mapped[float] = mapped_column(
        Float, default=0.95, nullable=False
    )  # 0.0 to 1.0 (Default: 95%)
    mode: Mapped[str] = mapped_column(
        String(32), default="companion", nullable=False
    )  # "companion" | "work"

    # Tool preferences and Google OAuth account linking
    disabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    google_refresh_token: Mapped[str | None] = mapped_column(EncryptedString(512), nullable=True)
    google_access_token: Mapped[str | None] = mapped_column(EncryptedString(1024), nullable=True)
    google_linked_email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    google_mock_linked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    google_client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    google_client_secret: Mapped[str | None] = mapped_column(EncryptedString(256), nullable=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="settings")

    @property
    def google_linked(self) -> bool:
        return bool(
            self.google_mock_linked or self.google_refresh_token or self.google_access_token
        )

    @google_linked.setter
    def google_linked(self, value: bool) -> None:
        if not value:
            self.google_mock_linked = False
            self.google_refresh_token = None
            self.google_access_token = None
            self.google_linked_email = None

    @property
    def google_is_mock(self) -> bool:
        return bool(self.google_mock_linked)

    @google_is_mock.setter
    def google_is_mock(self, value: bool) -> None:
        self.google_mock_linked = bool(value)

    @property
    def google_account_email(self) -> str | None:
        return self.google_linked_email

    @google_account_email.setter
    def google_account_email(self, value: str | None) -> None:
        self.google_linked_email = value

    def __repr__(self) -> str:
        return (
            f"<TARSSettings user_id={self.user_id!r} humor={self.humor_level} "
            f"honesty={self.honesty_level} mode={self.mode!r}>"
        )


__all__ = ["TARSSettings"]
