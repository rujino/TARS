"""TARS API Routers Package."""

from tars.api.routers.auth import router as auth_router
from tars.api.routers.chat import router as chat_router
from tars.api.routers.config import router as config_router

__all__ = [
    "auth_router",
    "chat_router",
    "config_router",
]
