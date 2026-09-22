"""OKF knowledge relevance and candidate scanner engine."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tars.core.database import get_session_factory
from tars.domains.knowledge.models import UserWikiIndex
from tars.domains.knowledge.spec.schemas import OKFImportance, OKFType
from tars.domains.proactive.scanner.schemas import ScanResult, UtteranceCandidate
from tars.domains.proactive.schemas import ScheduleType
from tars.domains.proactive.scorer.policy import DefaultReviewCyclePolicy, ReviewCyclePolicy

logger = logging.getLogger("tars.domains.proactive.scanner.engine")


class OKFRelevanceScanner:
    """Scans stored OKF knowledge indices to identify candidates due for proactive follow-up."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        review_policy: ReviewCyclePolicy | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.review_policy = review_policy or DefaultReviewCyclePolicy()

    async def scan_user(self, user_id: str) -> ScanResult:
        """Scan a specific user's OKF documents and return qualified utterance candidates."""
        now = datetime.now(UTC)
        candidates: list[UtteranceCandidate] = []
        scanned_count = 0

        async with self.session_factory() as session:
            stmt = (
                select(UserWikiIndex)
                .where(UserWikiIndex.user_id == user_id)
                .order_by(UserWikiIndex.updated_at.asc())
            )
            result = await session.execute(stmt)
            wikis = list(result.scalars().all())
            scanned_count = len(wikis)

            for wiki in wikis:
                try:
                    okf_type = OKFType(wiki.type)
                except ValueError:
                    okf_type = OKFType.CONCEPT

                try:
                    importance = OKFImportance(wiki.importance)
                except ValueError:
                    importance = OKFImportance.MEDIUM

                # Compute elapsed time in days since last update
                updated_at = wiki.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=UTC)
                else:
                    updated_at = updated_at.astimezone(UTC)

                elapsed_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
                recommended_cycle = self.review_policy.days_for(okf_type, importance)

                # Flag as candidate if review cycle threshold is reached or near
                if elapsed_days >= (recommended_cycle * 0.7):
                    candidate = UtteranceCandidate(
                        user_id=user_id,
                        schedule_type=ScheduleType.REVIEW_REMINDER,
                        okf_id=wiki.okf_id,
                        title=wiki.title,
                        okf_type=okf_type,
                        importance=importance,
                        elapsed_days=round(elapsed_days, 2),
                        review_cycle_days=recommended_cycle,
                        has_conversation_context=False,
                        raw_document_summary=f"[{wiki.type.upper()}] {wiki.title} (Category: {wiki.category or 'General'})",
                    )
                    candidates.append(candidate)

        return ScanResult(
            user_id=user_id,
            scanned_count=scanned_count,
            candidates=candidates,
            scanned_at_utc=now,
        )


__all__ = ["OKFRelevanceScanner"]
