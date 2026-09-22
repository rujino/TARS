"""Real-time WebSocket proactive delivery channel."""

from __future__ import annotations

import json
import logging

from tars.domains.proactive.delivery.base import DeliveryChannel, DeliveryResult
from tars.domains.proactive.schemas import ProactivePayload
from tars.runtime.proactive_connection_registry import ProactiveConnectionRegistry

logger = logging.getLogger("tars.domains.proactive.delivery.websocket")


class WebSocketDeliveryChannel(DeliveryChannel):
    """Real-time WebSocket streaming injector for active connected clients."""

    def __init__(self, registry: ProactiveConnectionRegistry | None = None) -> None:
        self.registry = registry or ProactiveConnectionRegistry.get_instance()

    @property
    def channel_name(self) -> str:
        return "websocket_live"

    async def is_available(self, user_id: str) -> bool:
        """Available if the user currently holds at least one open WebSocket."""
        return self.registry.is_connected(user_id)

    async def send(self, user_id: str, payload: ProactivePayload) -> DeliveryResult:
        """Inject proactive utterance into user's live WebSocket connection."""
        connections = self.registry.get_connections(user_id)
        if not connections:
            return DeliveryResult(
                channel_name=self.channel_name,
                success=False,
                error_detail="No active WebSocket connections found",
            )

        message_frame = {
            "type": "proactive_utterance",
            "payload": payload.model_dump(mode="json"),
        }
        serialized = json.dumps(message_frame, ensure_ascii=False)

        success_count = 0
        for ws in connections:
            try:
                await ws.send_text(serialized)
                success_count += 1
            except Exception as exc:
                logger.warning("Failed to send proactive utterance over WS to user '%s': %s", user_id, exc)

        if success_count > 0:
            logger.info("Successfully dispatched proactive WS message to user '%s' (%d sockets)", user_id, success_count)
            return DeliveryResult(channel_name=self.channel_name, success=True)

        return DeliveryResult(
            channel_name=self.channel_name,
            success=False,
            error_detail="Failed writing to all connected WebSockets",
        )


__all__ = ["WebSocketDeliveryChannel"]
