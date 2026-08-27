"""TARS Database Layer Package."""

from __future__ import annotations

from tars.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tars.db.models import (
    ChatMessage,
    ChatSession,
    TARSSettings,
    TarsSettings,
    User,
    UserWikiIndex,
    UserWikiMetadata,
)
from tars.db.session import (
    close_db,
    get_db,
    get_engine,
    get_sessionmaker,
    init_db,
)

__all__ = [
    "Base",
    "ChatMessage",
    "ChatSession",
    "TARSSettings",
    "TarsSettings",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserWikiIndex",
    "UserWikiMetadata",
    "close_db",
    "get_db",
    "get_engine",
    "get_sessionmaker",
    "init_db",
]
