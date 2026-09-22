"""REST API routes for proactive utterances, inbox queue, device tokens, and preferences."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.dependencies import get_current_user, get_db_session
from tars.domains.auth.models import User
from tars.domains.proactive.models import (
    ProactiveMessage,
    ProactiveSettings,
    UserDeviceToken,
)
from tars.domains.proactive.schemas import (
    DeviceTokenRegisterRequest,
    DeviceTokenResponse,
    ProactiveMessageResponse,
    ProactiveMessageStatus,
    ProactiveSettingsResponse,
    ProactiveSettingsUpdate,
)

logger = logging.getLogger("tars.domains.proactive.router")

router = APIRouter(prefix="/proactive", tags=["Proactive Utterance & Inbox"])


@router.get(
    "/inbox",
    response_model=list[ProactiveMessageResponse],
    summary="Get pending proactive messages",
)
async def get_proactive_inbox(
    status_filter: str = Query(
        default="pending",
        alias="status",
        description="Filter by status ('pending', 'delivered', 'read', 'dismissed', 'all')",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ProactiveMessage]:
    """Retrieve proactive utterances from the user's persistent inbox queue."""
    stmt = select(ProactiveMessage).where(ProactiveMessage.user_id == current_user.id)

    if status_filter != "all":
        stmt = stmt.where(ProactiveMessage.status == status_filter)

    stmt = stmt.order_by(desc(ProactiveMessage.scheduled_at)).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.put(
    "/inbox/{message_id}/read",
    response_model=ProactiveMessageResponse,
    summary="Mark proactive message as read",
)
async def mark_proactive_message_read(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProactiveMessage:
    """Transition a proactive message status to read."""
    stmt = select(ProactiveMessage).where(
        ProactiveMessage.id == message_id,
        ProactiveMessage.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proactive message not found",
        )

    message.status = ProactiveMessageStatus.READ.value
    await db.commit()
    await db.refresh(message)
    return message


@router.put(
    "/inbox/{message_id}/dismiss",
    response_model=ProactiveMessageResponse,
    summary="Dismiss a proactive message",
)
async def dismiss_proactive_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProactiveMessage:
    """Dismiss a proactive message without action."""
    stmt = select(ProactiveMessage).where(
        ProactiveMessage.id == message_id,
        ProactiveMessage.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proactive message not found",
        )

    message.status = ProactiveMessageStatus.DISMISSED.value
    await db.commit()
    await db.refresh(message)
    return message


@router.post(
    "/device-tokens",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register client device FCM push token",
)
async def register_device_token(
    request: DeviceTokenRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserDeviceToken:
    """Register or refresh an FCM push token for the current user's device."""
    stmt = select(UserDeviceToken).where(
        UserDeviceToken.user_id == current_user.id,
        UserDeviceToken.token == request.token,
    )
    result = await db.execute(stmt)
    token_entry = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if token_entry:
        token_entry.platform = request.platform
        token_entry.device_name = request.device_name
        token_entry.is_active = True
        token_entry.updated_at = now
    else:
        token_entry = UserDeviceToken(
            user_id=current_user.id,
            token=request.token,
            platform=request.platform,
            device_name=request.device_name,
            is_active=True,
        )
        db.add(token_entry)

    await db.commit()
    await db.refresh(token_entry)
    return token_entry


@router.delete(
    "/device-tokens/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete device push token on logout",
)
async def delete_device_token(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Remove a device token upon client logout."""
    stmt = delete(UserDeviceToken).where(
        UserDeviceToken.user_id == current_user.id,
        UserDeviceToken.token == token,
    )
    await db.execute(stmt)
    await db.commit()


@router.get(
    "/settings",
    response_model=ProactiveSettingsResponse,
    summary="Get user proactive preferences",
)
async def get_proactive_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProactiveSettings:
    """Retrieve personalized proactive settings for current user."""
    stmt = select(ProactiveSettings).where(ProactiveSettings.user_id == current_user.id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if not settings:
        settings = ProactiveSettings(user_id=current_user.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


@router.put(
    "/settings",
    response_model=ProactiveSettingsResponse,
    summary="Update user proactive preferences",
)
async def update_proactive_settings(
    request: ProactiveSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProactiveSettings:
    """Update personalized proactive utterance preferences."""
    stmt = select(ProactiveSettings).where(ProactiveSettings.user_id == current_user.id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if not settings:
        settings = ProactiveSettings(user_id=current_user.id)
        db.add(settings)

    if request.is_enabled is not None:
        settings.is_enabled = request.is_enabled
    if request.max_daily_proactive is not None:
        settings.max_daily_proactive = request.max_daily_proactive
    if request.quiet_hours_start is not None:
        settings.quiet_hours_start = request.quiet_hours_start
    if request.quiet_hours_end is not None:
        settings.quiet_hours_end = request.quiet_hours_end
    if request.timezone is not None:
        settings.timezone = request.timezone
    if request.enabled_types is not None:
        settings.enabled_types = [t.value for t in request.enabled_types]

    await db.commit()
    await db.refresh(settings)
    return settings


__all__ = ["router"]
