"""Database-backed Pending Inbox delivery channel."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tars.core.database import get_session_factory
from tars.domains.proactive.delivery.base import DeliveryChannel, DeliveryResult
from tars.domains.proactive.models import ProactiveMessage
from tars.domains.proactive.schemas import ProactiveMessageStatus, ProactivePayload

logger = logging.getLogger("tars.domains.proactive.delivery.inbox")


class InboxDeliveryChannel(DeliveryChannel):
    """Database-backed persistent inbox queue channel.

    Acts as the write-through persistence layer for all proactive utterances,
    ensuring messages remain available for offline clients and reconnection hydrations.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()

    @property
    def channel_name(self) -> str:
        return "inbox_db"

    async def is_available(self, user_id: str) -> bool:
        """Inbox queue is always available for write operations."""
        return True

    async def send(
        self,
        user_id: str,
        payload: ProactivePayload,
        delivered: bool = False,
    ) -> DeliveryResult:
        """Persist or update proactive message status in the database.

        Args:
            user_id: Target recipient user ID.
            payload: Standardized proactive utterance payload.
            delivered: Whether an upstream realtime channel (WebSocket / FCM) succeeded.
        """
        try:
            now = datetime.now(UTC)
            target_status = (
                ProactiveMessageStatus.DELIVERED if delivered else ProactiveMessageStatus.PENDING
            )

            async with self.session_factory() as session:
                async with session.begin():
                    # Check if message already exists by ID
                    stmt = select(ProactiveMessage).where(ProactiveMessage.id == payload.message_id)
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.status = target_status.value
                        if delivered:
                            existing.delivered_at = now
                    else:
                        message = ProactiveMessage(
                            id=payload.message_id,
                            user_id=user_id,
                            persona_id=payload.persona_id,
                            schedule_type=payload.schedule_type.value,
                            okf_id=payload.okf_id,
                            message_content=payload.content,
                            status=target_status.value,
                            scheduled_at=now,
                            delivered_at=now if delivered else None,
                        )
                        session.add(message)

            return DeliveryResult(channel_name=self.channel_name, success=True)
        except Exception as exc:
            logger.error(
                "Failed to persist proactive message '%s' in Inbox DB: %s",
                payload.message_id,
                exc,
                exc_info=True,
            )
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error_detail=str(exc),
            )


__all__ = ["InboxDeliveryChannel"]
