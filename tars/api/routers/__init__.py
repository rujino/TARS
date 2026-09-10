"""TARS API Routers Package."""

from fastapi import APIRouter

from tars.api.routers.auth import router as auth_router
from tars.api.routers.chat import router as chat_router
from tars.api.routers.config import router as config_router
from tars.api.routers.health import health_router
from tars.api.routers.tools import router as tools_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(config_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(tools_router)

__all__ = [
    "api_v1_router",
    "auth_router",
    "chat_router",
    "config_router",
    "health_router",
    "tools_router",
]
