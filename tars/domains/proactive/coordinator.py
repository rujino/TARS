"""Proactive utterance coordinator combining scanning, threshold scoring, synthesis, and delivery."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tars.core.database import get_session_factory
from tars.domains.proactive.delivery.router import DeliveryRouter
from tars.domains.proactive.generator.engine import ProactiveMessageGenerator
from tars.domains.proactive.generator.schemas import GeneratorInput
from tars.domains.proactive.models import ProactiveMessage, ProactiveSettings
from tars.domains.proactive.scanner.engine import OKFRelevanceScanner
from tars.domains.proactive.schemas import ProactivePayload, ScheduleType
from tars.domains.proactive.scorer.engine import UtteranceThresholdScorer

logger = logging.getLogger("tars.domains.proactive.coordinator")


class ProactiveCoordinator:
    """High-level coordinator executing end-to-end proactive utterance workflows."""

    def __init__(
        self,
        scanner: OKFRelevanceScanner | None = None,
        scorer: UtteranceThresholdScorer | None = None,
        generator: ProactiveMessageGenerator | None = None,
        delivery_router: DeliveryRouter | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.scanner = scanner or OKFRelevanceScanner(session_factory=self.session_factory)
        self.scorer = scorer or UtteranceThresholdScorer()
        self.generator = generator or ProactiveMessageGenerator()
        self.delivery_router = delivery_router or DeliveryRouter()

    async def execute_for_user(
        self,
        user_id: str,
        preferred_schedule_type: ScheduleType | None = None,
        target_okf_id: str | None = None,
    ) -> ProactivePayload | None:
        """Evaluate and dispatch proactive utterances for a specific user."""
        # 1. Fetch user preferences
        async with self.session_factory() as session:
            stmt = select(ProactiveSettings).where(ProactiveSettings.user_id == user_id)
            result = await session.execute(stmt)
            settings = result.scalar_one_or_none()

        if settings and not settings.is_enabled:
            logger.debug("Proactive utterances disabled for user '%s'", user_id)
            return None

        # 2. Check quiet hours in user's timezone
        tz_name = settings.timezone if settings else "Asia/Seoul"
        try:
            user_tz = ZoneInfo(tz_name)
        except Exception:
            user_tz = ZoneInfo("Asia/Seoul")

        now_local = datetime.now(user_tz)
        current_hour = now_local.hour

        if settings and settings.quiet_hours_start is not None and settings.quiet_hours_end is not None:
            start = settings.quiet_hours_start
            end = settings.quiet_hours_end
            in_quiet = (start <= current_hour < end) if start <= end else (current_hour >= start or current_hour < end)
            if in_quiet:
                logger.debug("Current hour %d is within quiet hours for user '%s'", current_hour, user_id)
                return None

        # 3. Calculate 24h fatigue and silence duration
        now_utc = datetime.now(UTC)
        async with self.session_factory() as session:
            # Count sends in last 24h
            stmt_count = select(func.count(ProactiveMessage.id)).where(
                ProactiveMessage.user_id == user_id,
                ProactiveMessage.scheduled_at >= datetime.fromtimestamp(now_utc.timestamp() - 86400, tz=UTC),
            )
            count_res = await session.execute(stmt_count)
            recent_sends = count_res.scalar_one()

            # Latest message
            stmt_last = (
                select(ProactiveMessage)
                .where(ProactiveMessage.user_id == user_id)
                .order_by(desc(ProactiveMessage.scheduled_at))
                .limit(1)
            )
            last_msg = (await session.execute(stmt_last)).scalar_one_or_none()

        hours_since_last: float | None = None
        if last_msg:
            last_time = last_msg.scheduled_at
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)
            hours_since_last = max(0.0, (now_utc - last_time).total_seconds() / 3600.0)

        # 4. Scan OKF documents
        scan_res = await self.scanner.scan_user(user_id)
        if not scan_res.candidates:
            logger.debug("No proactive candidates found for user '%s'", user_id)
            return None

        # Filter by target_okf_id if requested
        candidates = scan_res.candidates
        if target_okf_id:
            candidates = [c for c in candidates if c.okf_id == target_okf_id] or candidates

        # 5. Evaluate threshold score for each candidate
        qualified: list[tuple[float, Any]] = []
        for cand in candidates:
            verdict = self.scorer.evaluate(
                candidate=cand,
                recent_send_count=recent_sends,
                hours_since_last_send=hours_since_last,
            )
            if verdict.is_above_threshold:
                qualified.append((verdict.final_score, cand))

        if not qualified:
            logger.debug("All candidates fell below proactive activation threshold for user '%s'", user_id)
            return None

        # Sort by score descending and take highest candidate
        qualified.sort(key=lambda x: x[0], reverse=True)
        best_score, best_candidate = qualified[0]

        # 6. Synthesize utterance
        gen_input = GeneratorInput(
            user_id=user_id,
            persona_id="miu",  # Default system 1 persona or from settings
            schedule_type=best_candidate.schedule_type,
            okf_document_summary=best_candidate.raw_document_summary,
            okf_title=best_candidate.title,
            okf_importance=best_candidate.importance,
            temporal_context=now_local.strftime("%A %p %I시 %M분 (%Z)"),
            elapsed_days=best_candidate.elapsed_days,
            review_cycle_days=best_candidate.review_cycle_days,
            threshold_score=best_score,
        )

        gen_output = await self.generator.generate(gen_input)

        # 7. Assemble ProactivePayload
        msg_id = str(uuid.uuid4())
        payload = ProactivePayload(
            message_id=msg_id,
            persona_id=gen_output.persona_id,
            schedule_type=gen_output.schedule_type,
            content=gen_output.content,
            okf_id=best_candidate.okf_id,
            scheduled_at_utc=now_utc.isoformat(),
        )

        # 8. Deliver through channels (WS -> FCM -> Inbox)
        await self.delivery_router.deliver(user_id=user_id, payload=payload)
        return payload


__all__ = ["ProactiveCoordinator"]
