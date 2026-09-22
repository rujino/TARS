"""Firebase Cloud Messaging (FCM) push notification delivery channel."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tars.core.database import get_session_factory
from tars.domains.proactive.delivery.base import DeliveryChannel, DeliveryResult
from tars.domains.proactive.models import UserDeviceToken
from tars.domains.proactive.schemas import ProactivePayload

logger = logging.getLogger("tars.domains.proactive.delivery.fcm")

try:
    import firebase_admin
    from firebase_admin import credentials, messaging

    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False
    firebase_admin = None  # type: ignore[assignment]
    messaging = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]


def _ensure_firebase_initialized() -> bool:
    """Ensure Firebase Admin SDK app is initialized once."""
    if not HAS_FIREBASE or firebase_admin is None:
        return False
    if not firebase_admin._apps:
        try:
            from tars.config import get_settings

            settings = get_settings()
            if settings.firebase_credentials_path and credentials:
                cred = credentials.Certificate(settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})
            else:
                firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
            logger.info("Initialized Firebase Admin SDK for project '%s'", settings.firebase_project_id)
        except Exception as exc:
            logger.warning("Failed to initialize Firebase Admin SDK: %s", exc)
            return False
    return True


class FCMDeliveryChannel(DeliveryChannel):
    """Firebase Cloud Messaging push delivery channel.

    Zero-Platform Coupling:
        Dispatches 'data-only' payloads without OS notification banners.
        Clients natively decode the proactive payload and render UI banners.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()

    @property
    def channel_name(self) -> str:
        return "fcm_push"

    async def is_available(self, user_id: str) -> bool:
        """Available if Firebase Admin SDK is installed and user has registered active tokens."""
        if not HAS_FIREBASE:
            return False

        async with self.session_factory() as session:
            stmt = select(UserDeviceToken).where(
                UserDeviceToken.user_id == user_id,
                UserDeviceToken.is_active == True,  # noqa: E712
            ).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def send(self, user_id: str, payload: ProactivePayload) -> DeliveryResult:
        """Send data-only push notification to all active devices registered for user."""
        if not HAS_FIREBASE or messaging is None or not _ensure_firebase_initialized():
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error_detail="firebase-admin library is not initialized",
            )

        async with self.session_factory() as session:
            stmt = select(UserDeviceToken).where(
                UserDeviceToken.user_id == user_id,
                UserDeviceToken.is_active == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            tokens = list(result.scalars().all())

        if not tokens:
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error_detail="No active device tokens found for user",
            )

        payload_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        data_bundle = {
            "type": "proactive_utterance",
            "payload": payload_json,
        }

        apns_config = messaging.APNSConfig(
            headers={"apns-push-type": "background", "apns-priority": "5"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(content_available=True),
            ),
        )

        sent_count = 0
        invalid_tokens: list[str] = []

        for device in tokens:
            try:
                msg = messaging.Message(
                    data=data_bundle,
                    token=device.token,
                    apns=apns_config if device.platform == "ios" else None,
                )
                messaging.send(msg)
                sent_count += 1
            except Exception as exc:
                err_str = str(exc)
                logger.warning(
                    "FCM dispatch failed for token '%s' (user '%s'): %s",
                    device.token[:12],
                    user_id,
                    exc,
                )
                if "UNREGISTERED" in err_str or "invalid-registration-token" in err_str:
                    invalid_tokens.append(device.token)

        # Invalidate dead tokens asynchronously
        if invalid_tokens:
            async with self.session_factory() as session:
                async with session.begin():
                    stmt_update = (
                        update(UserDeviceToken)
                        .where(UserDeviceToken.token.in_(invalid_tokens))
                        .values(is_active=False)
                    )
                    await session.execute(stmt_update)
            logger.info("Deactivated %d unregistered FCM device tokens", len(invalid_tokens))

        if sent_count > 0:
            logger.info("Successfully pushed FCM proactive utterance to %d devices for user '%s'", sent_count, user_id)
            return DeliveryResult(channel_name=self.channel_name, success=True)

        return DeliveryResult(
            channel_name=self.channel_name,
            success=False,
            error_detail="All FCM token dispatches failed",
        )


__all__ = ["FCMDeliveryChannel"]
