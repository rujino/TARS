"""FastAPI dependency injection providers for TARS."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.config import get_settings
from tars.core.security import decode_access_token
from tars.db.models import User
from tars.db.session import get_session_factory
from tars.storage.manager import FileStorageManager

security_bearer = HTTPBearer(auto_error=False)


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


__all__ = [
    "get_current_user",
    "get_db_session",
    "get_storage_manager",
]
