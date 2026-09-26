"""TARS Central API Routers Package."""

from fastapi import APIRouter

from tars.api.routers.assets import router as assets_router
from tars.api.routers.health import health_router
from tars.domains.auth.router import router as auth_router
from tars.domains.chat.router import router as chat_router
from tars.domains.persona.router import router as persona_router
from tars.domains.proactive.router import router as proactive_router
from tars.domains.tools.router import router as tools_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(persona_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(tools_router)
api_v1_router.include_router(proactive_router)
api_v1_router.include_router(assets_router)

__all__ = [
    "api_v1_router",
    "assets_router",
    "auth_router",
    "chat_router",
    "health_router",
    "persona_router",
    "proactive_router",
    "tools_router",
]
