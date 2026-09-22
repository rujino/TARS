"""Global in-memory connection registry for proactive WebSocket streaming."""

from __future__ import annotations

import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger("tars.runtime.proactive_connection_registry")


class ProactiveConnectionRegistry:
    """Singleton tracking live active WebSockets keyed by user ID."""

    _instance: ProactiveConnectionRegistry | None = None

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    @classmethod
    def get_instance(cls) -> ProactiveConnectionRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, user_id: str, websocket: WebSocket) -> None:
        """Add active WebSocket connection for a user."""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)
        logger.debug("Registered proactive WS for user '%s' (active: %d)", user_id, len(self._connections[user_id]))

    def unregister(self, user_id: str, websocket: WebSocket) -> None:
        """Remove disconnected WebSocket."""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.debug("Unregistered proactive WS for user '%s'", user_id)

    def get_connections(self, user_id: str) -> list[WebSocket]:
        """Retrieve all currently connected open WebSockets for a user."""
        conns = self._connections.get(user_id, set())
        return [ws for ws in conns if ws.client_state == WebSocketState.CONNECTED]

    def is_connected(self, user_id: str) -> bool:
        """Check whether the user has at least one active open WebSocket."""
        return len(self.get_connections(user_id)) > 0


__all__ = ["ProactiveConnectionRegistry"]
