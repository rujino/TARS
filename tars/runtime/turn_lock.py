"""Hybrid Session Turn Lock (L1 in-memory mutex + L2 Redis distributed lock).

Implements Feature 15-20, 25:
- L1 in-memory mutex (asyncio.Lock)
- L2 Redis distributed lock (SET tars:session:{session_id}:lock {pod_id} NX PX 15000)
- 15s Watchdog TTL preventing orphan locks if pod hard-crashes
- 3s Background heartbeat lease renewal task using safe Lua script
- Safe Lua release (compare-and-delete) protecting stolen/successor pod locks
- Monotonic turn_epoch atomic issuance (HINCRBY) and tracking
- Local 0ms barge-in cancellation and Redis Pub/Sub cluster broadcast
- Graceful circuit breaker / fallback to L1 in-memory mutex logging REDIS_BACKPLANE_DEGRADED
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any

from tars.core.config import get_settings
from tars.runtime.redis_double import InMemoryAsyncRedis

logger = logging.getLogger("tars.runtime.turn_lock")

_redis_client_instance: Any = None


def get_redis_client() -> Any:
    """Return configured Redis client or InMemoryAsyncRedis fallback if Redis is enabled."""
    global _redis_client_instance
    if _redis_client_instance is not None:
        return _redis_client_instance

    settings = get_settings()
    if not settings.redis_enabled:
        return None

    try:
        import redis.asyncio as aioredis  # type: ignore

        _redis_client_instance = aioredis.from_url(
            settings.redis_url,
            socket_timeout=settings.redis_socket_timeout,
            max_connections=settings.redis_max_connections,
        )
    except Exception as exc:
        logger.warning(
            "REDIS_BACKPLANE_DEGRADED: Real redis client unavailable (%s); using InMemoryAsyncRedis",
            exc,
        )
        _redis_client_instance = InMemoryAsyncRedis()

    return _redis_client_instance


def set_redis_client(client: Any) -> None:
    """Explicitly inject a Redis client (useful for tests and dependency injection)."""
    global _redis_client_instance
    _redis_client_instance = client


class TurnState(str, Enum):
    """Lifecycle states of a session turn."""

    IDLE = "IDLE"
    USER_BUFFERING = "USER_BUFFERING"
    DIRECTOR_EVAL = "DIRECTOR_EVAL"
    GENERATING = "GENERATING"
    GAP_WAITING = "GAP_WAITING"
    ABORTING = "ABORTING"


class LockContentionError(Exception):
    """Raised when a session turn lock cannot be acquired due to active contention."""


@dataclass
class StreamPacket:
    """Stream token packet stamped with turn generation epoch for 0ms drop guard."""

    turn_epoch: int
    content: str
    is_interrupted: bool = False
    sender: str | None = None


class HybridSessionTurnLock:
    """L1 (asyncio.Lock) + L2 (Redis SET NX PX 15000) Hybrid Session Turn Lock."""

    LUA_SAFE_UNLOCK = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    LUA_SAFE_EXTEND = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("pexpire", KEYS[1], ARGV[2])
    else
        return 0
    end
    """

    def __init__(
        self,
        session_id: str,
        pod_id: str = "pod-primary-1",
        redis_client: Any = None,
        watchdog_ttl_ms: int = 15000,
        heartbeat_interval: float = 3.0,
    ) -> None:
        self.session_id = session_id
        self.pod_id = pod_id
        if redis_client is None:
            redis_client = get_redis_client()
        self.redis = redis_client
        self.watchdog_ttl_ms = watchdog_ttl_ms
        self.heartbeat_interval = heartbeat_interval

        self.lock_key = f"tars:session:{session_id}:lock"
        self.state_key = f"tars:session:{session_id}:turn"
        self.channel_key = f"tars:session:{session_id}:events"

        self.local_mutex = asyncio.Lock()
        self.abort_event = asyncio.Event()
        self.local_epoch: int = 0
        self.state: TurnState = TurnState.IDLE
        self.current_speaker: str | None = None
        self.active_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.redis_degraded: bool = False

    async def acquire_turn(self, speaker: str) -> int:
        """Acquire turn lock with L1 mutex and L2 Redis distributed lock.

        Returns:
            The acquired monotonic turn_epoch integer.

        Raises:
            LockContentionError: If the lock is held by another entity.
        """
        if self.local_mutex.locked() or self.state != TurnState.IDLE:
            raise LockContentionError(
                f"Session turn '{self.session_id}' currently locked by another entity on this pod."
            )
        await self.local_mutex.acquire()
        try:
            if self.redis and not self.redis_degraded:
                try:
                    acquired = await self.redis.set(
                        self.lock_key,
                        self.pod_id,
                        nx=True,
                        px=self.watchdog_ttl_ms,
                    )
                    if not acquired:
                        raise LockContentionError(
                            f"Session turn '{self.session_id}' currently locked by another entity."
                        )

                    self.local_epoch = await self.redis.hincrby(self.state_key, "turn_epoch", 1)
                    await self.redis.hset(
                        self.state_key,
                        mapping={
                            "state": TurnState.GENERATING.value,
                            "current_speaker": speaker,
                            "active_pod": self.pod_id,
                            "turn_epoch": str(self.local_epoch),
                            "updated_at": str(time.time()),
                        },
                    )
                    self._start_watchdog()
                except LockContentionError:
                    raise
                except (ConnectionError, TimeoutError, OSError) as exc:
                    logger.warning(
                        "REDIS_BACKPLANE_DEGRADED: Falling back to local L1 in-memory mutex (%s)",
                        exc,
                    )
                    self.redis_degraded = True
                    self.local_epoch += 1
            else:
                self.local_epoch += 1

            self.state = TurnState.GENERATING
            self.current_speaker = speaker
            self.abort_event.clear()
            return self.local_epoch
        except BaseException:
            if self.local_mutex.locked():
                self.local_mutex.release()
            raise

    async def release_turn(self) -> None:
        """Safely release turn lock using atomic Lua compare-and-delete."""
        self._stop_watchdog()

        if self.redis and not self.redis_degraded:
            try:
                res = await self.redis.eval(
                    self.LUA_SAFE_UNLOCK,
                    1,
                    self.lock_key,
                    self.pod_id,
                )
                if res == 1:
                    await self.redis.hset(self.state_key, mapping={"state": TurnState.IDLE.value})
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.warning(
                    "REDIS_BACKPLANE_DEGRADED: Failed to release Redis lock cleanly (%s)", exc
                )
                self.redis_degraded = True

        self.state = TurnState.IDLE
        self.current_speaker = None
        if self.local_mutex.locked():
            self.local_mutex.release()

    @asynccontextmanager
    async def hold(self, speaker: str) -> AsyncIterator[int]:
        """Context manager to acquire and automatically release turn lock."""
        epoch = await self.acquire_turn(speaker)
        try:
            yield epoch
        finally:
            await self.release_turn()

    def _start_watchdog(self) -> None:
        self._stop_watchdog()
        self._heartbeat_task = asyncio.create_task(self._watchdog_loop())

    def _stop_watchdog(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _watchdog_loop(self) -> None:
        """Periodically renew Redis lock TTL using Lua safe extend."""
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                if self.redis and not self.redis_degraded:
                    try:
                        res = await self.redis.eval(
                            self.LUA_SAFE_EXTEND,
                            1,
                            self.lock_key,
                            self.pod_id,
                            self.watchdog_ttl_ms,
                        )
                        if res == 0:
                            # Lock was stolen or expired; cancel turn
                            logger.warning(
                                "Lock lease renewal failed (lock expired or stolen by another pod)"
                            )
                            self.abort_event.set()
                            if self.active_task and not self.active_task.done():
                                self.active_task.cancel()
                            break
                    except (ConnectionError, TimeoutError, OSError) as exc:
                        logger.warning(
                            "REDIS_BACKPLANE_DEGRADED: Watchdog renewal exception (%s)", exc
                        )
                        self.redis_degraded = True
                        break
        except asyncio.CancelledError:
            pass

    async def trigger_barge_in(self) -> None:
        """Trigger local and cluster-wide 0ms barge-in cancellation."""
        self.abort_event.set()
        self.local_epoch += 1
        self.state = TurnState.ABORTING

        if self.active_task and not self.active_task.done():
            self.active_task.cancel()

        if self.redis and not self.redis_degraded:
            try:
                await self.redis.publish(
                    self.channel_key,
                    json.dumps(
                        {
                            "action": "barge_in",
                            "session_id": self.session_id,
                            "epoch": self.local_epoch,
                            "pod_id": self.pod_id,
                            "timestamp": time.time(),
                        }
                    ),
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.warning(
                    "REDIS_BACKPLANE_DEGRADED: Barge-in pub/sub broadcast failed (%s)", exc
                )
                self.redis_degraded = True

    def filter_packet(self, packet: StreamPacket) -> bool:
        """0ms packet filter: drops packet immediately if turn_epoch != local_epoch."""
        return packet.turn_epoch == self.local_epoch

    def is_aborted(self) -> bool:
        """Check if turn has been aborted."""
        return self.abort_event.is_set()
