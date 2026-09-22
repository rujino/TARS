"""Delivery router orchestrating fallback chains and write-through inbox persistence."""

from __future__ import annotations

import logging

from tars.domains.proactive.delivery.base import DeliveryResult
from tars.domains.proactive.delivery.fcm import FCMDeliveryChannel
from tars.domains.proactive.delivery.inbox import InboxDeliveryChannel
from tars.domains.proactive.delivery.websocket import WebSocketDeliveryChannel
from tars.domains.proactive.schemas import ProactivePayload

logger = logging.getLogger("tars.domains.proactive.delivery.router")


class DeliveryRouter:
    """Orchestrates proactive message delivery across WebSocket, FCM push, and DB Inbox queue.

    Delivery Pipeline:
        1. WebSocket live injection (if client is actively connected)
        2. Firebase FCM push notification fallback (if client is offline but registered token)
        3. Database Inbox queue persistence (write-through executed unconditionally)
    """

    def __init__(
        self,
        ws_channel: WebSocketDeliveryChannel | None = None,
        fcm_channel: FCMDeliveryChannel | None = None,
        inbox_channel: InboxDeliveryChannel | None = None,
    ) -> None:
        self.ws_channel = ws_channel or WebSocketDeliveryChannel()
        self.fcm_channel = fcm_channel or FCMDeliveryChannel()
        self.inbox_channel = inbox_channel or InboxDeliveryChannel()

    async def deliver(
        self,
        user_id: str,
        payload: ProactivePayload,
    ) -> list[DeliveryResult]:
        """Attempt delivery through prioritized channels and persist to inbox.

        Returns:
            List of DeliveryResult objects for audit logging.
        """
        results: list[DeliveryResult] = []
        is_delivered = False

        # 1. Attempt WebSocket live stream
        if await self.ws_channel.is_available(user_id):
            ws_res = await self.ws_channel.send(user_id, payload)
            results.append(ws_res)
            if ws_res.success:
                is_delivered = True

        # 2. If WS was not available or failed, fallback to FCM push
        if not is_delivered and await self.fcm_channel.is_available(user_id):
            fcm_res = await self.fcm_channel.send(user_id, payload)
            results.append(fcm_res)
            if fcm_res.success:
                is_delivered = True

        # 3. Always persist to Inbox DB (Write-Through)
        inbox_res = await self.inbox_channel.send(user_id, payload, delivered=is_delivered)
        results.append(inbox_res)

        logger.info(
            "Proactive delivery completed for msg '%s' (user: '%s', delivered: %s, attempts: %d)",
            payload.message_id,
            user_id,
            is_delivered,
            len(results),
        )
        return results


__all__ = ["DeliveryRouter"]
