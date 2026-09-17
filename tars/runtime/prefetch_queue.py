"""Overlapping secondary speaker prefetch queue with organic breathing jitter bâton touch.

Implements Features 21-24:
- Buffering secondary speaker tokens during primary streaming
- Deterministic trigger: sentence punctuation ('.', '!', '?', '\n') or 30 cumulative tokens
- Seamless bâton touch with 0.2s organic breathing jitter delay followed by immediate burst
- 0ms abort_and_discard() garbage collection on barge-in
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

logger = logging.getLogger("tars.runtime.prefetch_queue")


class PrefetchBufferQueue:
    """In-memory async buffer queue for overlapping secondary speaker token prefetching."""

    SENTENCE_TERMINATORS: tuple[str, ...] = (".", "!", "?", "\n")

    def __init__(
        self,
        secondary_speaker: str = "",
        target_epoch: int = 0,
        session_id: str | None = None,
        speaker: str | None = None,
    ) -> None:
        self.speaker = speaker or secondary_speaker
        self.secondary_speaker = self.speaker
        self.target_epoch = target_epoch
        self.session_id = session_id or ""

        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.buffered_chunks: list[str] = []
        self.prefetch_task: asyncio.Task[None] | None = None
        self.is_aborted: bool = False
        self.is_triggered: bool = False

    def should_trigger(self, primary_delta: str, cumulative_tokens: int) -> bool:
        """Deterministic trigger: sentence punctuation or 30 cumulative tokens.

        Returns True on first detection, and False subsequently.
        """
        if self.is_triggered:
            return False
        if any(p in primary_delta for p in self.SENTENCE_TERMINATORS) or cumulative_tokens >= 30:
            self.is_triggered = True
            return True
        return False

    async def push_chunk(self, chunk: str) -> None:
        """Buffer a single prefetch token chunk into internal queue."""
        if not self.is_aborted:
            self.buffered_chunks.append(chunk)
            await self.queue.put(chunk)

    def start_prefetch(self, generator_fn: Callable[[], AsyncIterator[str]]) -> None:
        """Spawn background coroutine producing tokens into buffer queue."""
        self.prefetch_task = asyncio.create_task(self._producer_loop(generator_fn))

    async def _producer_loop(self, generator_fn: Callable[[], AsyncIterator[str]]) -> None:
        try:
            async for token in generator_fn():
                if self.is_aborted:
                    break
                self.buffered_chunks.append(token)
                await self.queue.put(token)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Prefetch producer failed: %s", exc)
        finally:
            await self.queue.put(None)  # Sentinel indicating generation end

    async def drain_baton_touch(
        self,
        jitter_gap: float = 0.2,
        check_abort_fn: Callable[[], bool] | None = None,
        current_epoch_fn: Callable[[], int] | None = None,
    ) -> AsyncIterator[str]:
        """Wait organic breathing jitter delay (0.2s), then burst-drain buffered tokens.

        Terminates immediately if aborted before or during token delivery.
        """
        if (
            self.is_aborted
            or (check_abort_fn and check_abort_fn())
            or (current_epoch_fn and current_epoch_fn() != self.target_epoch)
        ):
            return

        if jitter_gap > 0:
            await asyncio.sleep(jitter_gap)

        if (
            self.is_aborted
            or (check_abort_fn and check_abort_fn())
            or (current_epoch_fn and current_epoch_fn() != self.target_epoch)
        ):
            return

        while True:
            token = await self.queue.get()
            if token is None:
                break
            if (
                self.is_aborted
                or (check_abort_fn and check_abort_fn())
                or (current_epoch_fn and current_epoch_fn() != self.target_epoch)
            ):
                break
            yield token

    def abort_and_discard(self) -> None:
        """Instant garbage collection: cancels prefetch task, purges queue, and resets state."""
        self.is_aborted = True
        if self.prefetch_task and not self.prefetch_task.done():
            self.prefetch_task.cancel()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.buffered_chunks.clear()
        self.queue.put_nowait(None)
