"""High-fidelity In-Memory Async Redis test double for offline and CI environments.

Implements core primitives for distributed locking, hash storage, pub/sub,
and atomic Lua script evaluations (safe unlock and safe lease renewal).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger("tars.runtime.redis_double")


class InMemoryPubSub:
    """Pub/Sub client simulation for InMemoryAsyncRedis."""

    def __init__(self, redis_double: InMemoryAsyncRedis) -> None:
        self._redis = redis_double
        self._channels: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listener_task: asyncio.Task[None] | None = None
        self._closed: bool = False

    async def subscribe(self, *channels: str) -> None:
        """Subscribe to one or more channel names."""
        for ch in channels:
            if ch not in self._channels:
                self._channels.add(ch)
                q = self._redis.subscribe(ch)
                # Background forwarder for this channel
                asyncio.create_task(self._forward_messages(ch, q))
                await self._queue.put(
                    {"type": "subscribe", "channel": ch, "data": len(self._channels)}
                )

    async def _forward_messages(self, channel: str, q: asyncio.Queue[str]) -> None:
        try:
            while True:
                msg = await q.get()
                if self._closed:
                    break
                await self._queue.put({"type": "message", "channel": channel, "data": msg})
        except asyncio.CancelledError:
            pass

    async def unsubscribe(self, *channels: str) -> None:
        """Unsubscribe from specified channels."""
        for ch in channels:
            self._channels.discard(ch)
            await self._queue.put(
                {"type": "unsubscribe", "channel": ch, "data": len(self._channels)}
            )

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float | None = 0.0,
    ) -> dict[str, Any] | None:
        """Fetch next message from queue."""
        if self._closed:
            return None
        try:
            if timeout is None or timeout <= 0.0:
                msg = self._queue.get_nowait()
            else:
                msg = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except (asyncio.QueueEmpty, TimeoutError):
            return None

        if ignore_subscribe_messages and msg.get("type") in ("subscribe", "unsubscribe"):
            return await self.get_message(ignore_subscribe_messages=True, timeout=timeout)
        return msg

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Asynchronously iterate over incoming pub/sub messages."""
        while not self._closed:
            try:
                msg = await self._queue.get()
                if msg.get("type") == "message":
                    yield msg
            except asyncio.CancelledError:
                break

    async def close(self) -> None:
        """Close this pubsub subscription."""
        self._closed = True
        self._channels.clear()

    async def aclose(self) -> None:
        """Async alias for close."""
        await self.close()


class InMemoryAsyncRedis:
    """In-memory async Redis test double supporting distributed locking, hashes, pub/sub, and Lua scripts."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}  # key -> (value, expire_at_timestamp)
        self._hashes: dict[str, dict[str, str]] = {}
        self._channels: dict[str, list[asyncio.Queue[str]]] = {}
        self.fail_all_operations: bool = False

    def _check_failure(self) -> None:
        if self.fail_all_operations:
            raise ConnectionError("Redis cluster connection refused (simulated backplane outage)")

    def _is_expired(self, key: str) -> bool:
        if key not in self._store:
            return True
        _, exp = self._store[key]
        if exp is not None and time.time() >= exp:
            del self._store[key]
            return True
        return False

    async def ping(self) -> bool:
        """Check connection health."""
        self._check_failure()
        return True

    async def get(self, key: str) -> str | None:
        """Get string value by key."""
        self._check_failure()
        if self._is_expired(key):
            return None
        val, _ = self._store[key]
        return val

    async def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool:
        """Set key to value with optional NX (only if not exists) and PX/EX expiration."""
        self._check_failure()
        now = time.time()
        key_exists = not self._is_expired(key)

        if nx and key_exists:
            return False

        expire_at: float | None = None
        if px is not None:
            expire_at = now + (px / 1000.0)
        elif ex is not None:
            expire_at = now + float(ex)

        self._store[key] = (str(value), expire_at)
        return True

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        self._check_failure()
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
            if k in self._hashes:
                del self._hashes[k]
                count += 1
        return count

    async def pexpire(self, key: str, milliseconds: int) -> int:
        """Set key expiration in milliseconds."""
        self._check_failure()
        if self._is_expired(key):
            return 0
        val, _ = self._store[key]
        self._store[key] = (val, time.time() + (milliseconds / 1000.0))
        return 1

    async def expire(self, key: str, seconds: int) -> int:
        """Set key expiration in seconds."""
        return await self.pexpire(key, seconds * 1000)

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        """Increment integer value of hash field."""
        self._check_failure()
        if key not in self._hashes:
            self._hashes[key] = {}
        curr = int(self._hashes[key].get(field, "0"))
        new_val = curr + amount
        self._hashes[key][field] = str(new_val)
        return new_val

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: Any = None,
        mapping: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Set field(s) in a Redis hash."""
        self._check_failure()
        if key not in self._hashes:
            self._hashes[key] = {}

        count = 0
        if mapping is not None:
            for k, v in mapping.items():
                self._hashes[key][str(k)] = str(v)
                count += 1
        if field is not None and value is not None:
            self._hashes[key][str(field)] = str(value)
            count += 1
        for k, v in kwargs.items():
            self._hashes[key][str(k)] = str(v)
            count += 1
        return count

    async def hget(self, key: str, field: str) -> str | None:
        """Get field value from a hash."""
        self._check_failure()
        if key not in self._hashes:
            return None
        return self._hashes[key].get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all fields and values in a hash."""
        self._check_failure()
        if key not in self._hashes:
            return {}
        return dict(self._hashes[key])

    async def publish(self, channel: str, message: str) -> int:
        """Publish message to channel subscribers."""
        self._check_failure()
        queues = self._channels.get(channel, [])
        for q in queues:
            await q.put(message)
        return len(queues)

    def subscribe(self, channel: str) -> asyncio.Queue[str]:
        """Direct queue subscription helper."""
        q: asyncio.Queue[str] = asyncio.Queue()
        if channel not in self._channels:
            self._channels[channel] = []
        self._channels[channel].append(q)
        return q

    def pubsub(self) -> InMemoryPubSub:
        """Return a PubSub helper client instance."""
        return InMemoryPubSub(self)

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        """Simulate Lua atomic scripts for safe unlock and safe lease extension."""
        self._check_failure()
        keys = keys_and_args[:numkeys]
        args = keys_and_args[numkeys:]

        # Safe Unlock: if get(key) == arg: del(key); return 1 else return 0
        if "del" in script.lower() and "get" in script.lower():
            target_key = keys[0]
            expected_val = str(args[0])
            actual_val = await self.get(target_key)
            if actual_val == expected_val:
                await self.delete(target_key)
                return 1
            return 0

        # Safe Extend: if get(key) == arg1: pexpire(key, arg2); return 1 else return 0
        if "pexpire" in script.lower() and "get" in script.lower():
            target_key = keys[0]
            expected_val = str(args[0])
            pexpire_ms = int(args[1])
            actual_val = await self.get(target_key)
            if actual_val == expected_val:
                await self.pexpire(target_key, pexpire_ms)
                return 1
            return 0

        raise NotImplementedError(
            f"Lua script pattern not modeled in test double: {script[:50]}..."
        )

    async def close(self) -> None:
        """Close in-memory connection and purge resources."""
        self._store.clear()
        self._hashes.clear()
        self._channels.clear()

    async def aclose(self) -> None:
        """Async alias for close."""
        await self.close()
