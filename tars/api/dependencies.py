"""FastAPI dependency injection providers for TARS."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.config import get_settings
from tars.core.database import get_session_factory
from tars.core.security import decode_access_token
from tars.domains.auth.models import User
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.tools.google.calendar import GoogleCalendarAdapter
from tars.domains.tools.google.gmail import GmailAdapter
from tars.domains.tools.mcp.adapter import register_mcp_server_tools
from tars.domains.tools.mcp.client import AsyncMCPClient
from tars.domains.tools.mcp.models import MCPServerConfig
from tars.domains.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.dependencies")

security_bearer = HTTPBearer(auto_error=False)

_global_tool_registry: ToolRegistry | None = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session with automatic cleanup."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_storage_manager() -> FileStorageManager:
    """Provide the application file storage manager."""
    settings = get_settings()
    return FileStorageManager(base_dir=settings.storage_dir)


async def build_tool_registry() -> ToolRegistry:
    """Instantiate and populate a ToolRegistry with default Google and MCP tools."""
    settings = get_settings()
    registry = ToolRegistry()

    # 1. Google Workspace tools
    calendar_adapter = GoogleCalendarAdapter()
    gmail_adapter = GmailAdapter()
    registry.register_many(calendar_adapter.get_tools())
    registry.register_many(gmail_adapter.get_tools())
    registry.track_client(calendar_adapter)
    registry.track_client(gmail_adapter)

    # 2. Configured MCP server tools
    for srv_cfg in settings.mcp_servers:
        try:
            client = AsyncMCPClient(config=MCPServerConfig(**srv_cfg))
            await register_mcp_server_tools(client=client, registry=registry)
            registry.track_client(client)
        except Exception as exc:
            logger.warning(
                "Failed to register MCP server '%s': %s",
                srv_cfg.get("name", "unknown"),
                exc,
            )

    return registry


async def get_tool_registry() -> ToolRegistry:
    """Provide the application ToolRegistry singleton."""
    global _global_tool_registry
    if _global_tool_registry is None:
        _global_tool_registry = await build_tool_registry()
    return _global_tool_registry


async def close_tool_registry() -> None:
    """Gracefully close the global tool registry and associated clients."""
    global _global_tool_registry
    if _global_tool_registry is not None:
        await _global_tool_registry.aclose()
        _global_tool_registry = None


async def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Security(security_bearer),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Authenticate request using Bearer JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if auth is None or not auth.credentials:
        raise credentials_exception

    token = auth.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account",
        )

    return user


async def get_agent_chat_service(
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorageManager = Depends(get_storage_manager),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> Any:
    """Provide initialized AgentChatService instance."""
    from tars.domains.chat.services.agent_chat import AgentChatService

    return AgentChatService(
        db_session=db,
        storage_manager=storage,
        tool_registry=tool_registry,
    )


async def get_proactive_greeting_service(
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorageManager = Depends(get_storage_manager),
) -> Any:
    """Provide initialized ProactiveGreetingService instance."""
    from tars.domains.chat.services.greeting import ProactiveGreetingService
    from tars.engine.adapters.gemini import GeminiAdapter
    from tars.engine.adapters.llamacpp import LlamaCppAdapter
    from tars.engine.adapters.router import HybridLLMRouter

    llm_router = HybridLLMRouter(gemini_adapter=GeminiAdapter(), slm_adapter=LlamaCppAdapter())
    return ProactiveGreetingService(
        db_session=db,
        storage_manager=storage,
        llm_adapter=llm_router,
    )


async def get_auth_service(
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Provide initialized AuthService instance."""
    from tars.domains.auth.service import AuthService

    return AuthService(db=db)


async def get_user_settings_service(
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Provide initialized UserSettingsService instance."""
    from tars.domains.persona.service import UserSettingsService

    return UserSettingsService(db=db)


async def get_tool_service(
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> Any:
    """Provide initialized ToolService instance."""
    from tars.domains.tools.service import ToolService

    return ToolService(db=db, tool_registry=tool_registry, settings=get_settings())


__all__ = [
    "close_tool_registry",
    "get_agent_chat_service",
    "get_auth_service",
    "get_current_user",
    "get_db_session",
    "get_proactive_greeting_service",
    "get_storage_manager",
    "get_tool_registry",
    "get_tool_service",
    "get_user_settings_service",
]
