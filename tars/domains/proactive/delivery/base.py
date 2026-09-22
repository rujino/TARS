"""Base delivery abstractions and channel contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tars.domains.proactive.schemas import ProactivePayload


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of an utterance delivery attempt over a specific channel."""

    channel_name: str
    success: bool
    error_detail: str | None = None


class DeliveryChannel(ABC):
    """Abstract base class for proactive utterance delivery channels.

    Strategy pattern: Concrete implementations handle WebSocket, FCM, or Inbox persistence.
    Adding a new channel requires creating an implementation here without changing
    the upstream generator or scheduler layers.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Unique identifier for logging and telemetry."""
        ...

    @abstractmethod
    async def send(self, user_id: str, payload: ProactivePayload) -> DeliveryResult:
        """Deliver the proactive payload to the target user."""
        ...

    @abstractmethod
    async def is_available(self, user_id: str) -> bool:
        """Determine whether this channel can currently reach the target user."""
        ...


__all__ = ["DeliveryChannel", "DeliveryResult"]
