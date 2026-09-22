"""Proactive utterance scheduler engine supporting database persistence and graceful recovery."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tars.core.database import get_session_factory
from tars.domains.proactive.models import ProactiveScheduleEntry
from tars.domains.proactive.scheduler.schemas import ScheduledJobInfo
from tars.domains.proactive.schemas import ScheduleType

logger = logging.getLogger("tars.domains.proactive.scheduler.engine")

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.date import DateTrigger

    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
    DateTrigger = None  # type: ignore[assignment,misc]


class ProactiveScheduler:
    """Manages proactive scanning and delivery jobs.

    Features:
        - Backed by SQLAlchemy ProactiveScheduleEntry table for survival across reboots.
        - Utilizes APScheduler AsyncIOScheduler when available, with internal task fallback.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        job_handler: Callable[[str, ScheduleType, str | None], Any] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.job_handler = job_handler
        self._is_running = False
        self._apscheduler: Any | None = None
        self._poll_task: asyncio.Task[None] | None = None

        if HAS_APSCHEDULER and AsyncIOScheduler is not None:
            self._apscheduler = AsyncIOScheduler(timezone=UTC)

    async def start(self) -> None:
        """Initialize scheduler, restore persisted jobs from DB, and start loop."""
        if self._is_running:
            return

        self._is_running = True
        logger.info(
            "Starting ProactiveScheduler (APScheduler backend: %s)",
            "Active" if self._apscheduler else "Fallback Poller",
        )

        if self._apscheduler:
            self._apscheduler.start()

        # Restore active jobs from DB
        await self._restore_persisted_jobs()

        # Start periodic polling task for due jobs
        self._poll_task = asyncio.create_task(self._poll_due_jobs_loop())

    async def shutdown(self) -> None:
        """Gracefully terminate scheduler and cancel ongoing background tasks."""
        if not self._is_running:
            return

        self._is_running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._apscheduler:
            self._apscheduler.shutdown(wait=False)

        logger.info("ProactiveScheduler terminated cleanly")

    async def register_scan_job(
        self,
        user_id: str,
        run_at: datetime,
        schedule_type: ScheduleType,
        okf_id: str | None = None,
    ) -> str:
        """Register a new proactive run job in both database and scheduler memory."""
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)
        else:
            run_at = run_at.astimezone(UTC)

        entry_id = str(uuid.uuid4())

        async with self.session_factory() as session:
            async with session.begin():
                entry = ProactiveScheduleEntry(
                    id=entry_id,
                    user_id=user_id,
                    okf_id=okf_id,
                    schedule_type=schedule_type.value,
                    next_run_at=run_at,
                    is_active=True,
                )
                session.add(entry)

        # Schedule in APScheduler if available
        if self._apscheduler and DateTrigger:
            try:
                self._apscheduler.add_job(
                    self._execute_job,
                    trigger=DateTrigger(run_date=run_at, timezone=UTC),
                    id=entry_id,
                    args=[entry_id, user_id, schedule_type, okf_id],
                    replace_existing=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to register job '%s' with APScheduler: %s",
                    entry_id,
                    exc,
                )

        logger.info(
            "Registered proactive job '%s' for user '%s' at %s",
            entry_id,
            user_id,
            run_at.isoformat(),
        )
        return entry_id

    async def cancel_job(self, entry_id: str) -> bool:
        """Deactivate a job in the database and remove it from scheduler memory."""
        async with self.session_factory() as session:
            async with session.begin():
                stmt = (
                    update(ProactiveScheduleEntry)
                    .where(ProactiveScheduleEntry.id == entry_id)
                    .values(is_active=False)
                )
                result = await session.execute(stmt)
                updated = result.rowcount > 0

        if self._apscheduler:
            try:
                self._apscheduler.remove_job(entry_id)
            except Exception:
                pass

        return bool(updated)

    async def _restore_persisted_jobs(self) -> None:
        """Hydrate pending active jobs from database on startup."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            stmt = select(ProactiveScheduleEntry).where(
                ProactiveScheduleEntry.is_active == True,  # noqa: E712
                ProactiveScheduleEntry.next_run_at >= now,
            )
            result = await session.execute(stmt)
            active_entries = list(result.scalars().all())

        count = len(active_entries)
        for entry in active_entries:
            if self._apscheduler and DateTrigger:
                try:
                    self._apscheduler.add_job(
                        self._execute_job,
                        trigger=DateTrigger(run_date=entry.next_run_at, timezone=UTC),
                        id=entry.id,
                        args=[
                            entry.id,
                            entry.user_id,
                            ScheduleType(entry.schedule_type),
                            entry.okf_id,
                        ],
                        replace_existing=True,
                    )
                except Exception as exc:
                    logger.warning("Failed to restore job '%s': %s", entry.id, exc)

        logger.info("Restored %d active proactive jobs from DB", count)

    async def _execute_job(
        self,
        entry_id: str,
        user_id: str,
        schedule_type: ScheduleType,
        okf_id: str | None,
    ) -> None:
        """Execute scheduled proactive job handler and mark entry inactive."""
        logger.info("Executing proactive job '%s' (%s) for user '%s'", entry_id, schedule_type, user_id)
        try:
            if self.job_handler:
                res = self.job_handler(user_id, schedule_type, okf_id)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as exc:
            logger.error("Error executing proactive job '%s': %s", entry_id, exc, exc_info=True)
        finally:
            # Mark job completed in DB
            await self.cancel_job(entry_id)

    async def _poll_due_jobs_loop(self) -> None:
        """Periodic background loop checking for due jobs (acts as fallback or standalone poller)."""
        while self._is_running:
            try:
                await asyncio.sleep(60)  # Check every minute
                now = datetime.now(UTC)
                async with self.session_factory() as session:
                    stmt = (
                        select(ProactiveScheduleEntry)
                        .where(
                            ProactiveScheduleEntry.is_active == True,  # noqa: E712
                            ProactiveScheduleEntry.next_run_at <= now,
                        )
                        .limit(20)
                    )
                    result = await session.execute(stmt)
                    due_entries = list(result.scalars().all())

                for entry in due_entries:
                    # Execute due entries if not already dispatched by APScheduler
                    await self._execute_job(
                        entry.id,
                        entry.user_id,
                        ScheduleType(entry.schedule_type),
                        entry.okf_id,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in proactive job poller: %s", exc)


__all__ = ["ProactiveScheduler"]
