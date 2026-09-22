"""Tier 1 Unit tests for TARS Proactive Utterance Engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tars.domains.knowledge.spec.schemas import OKFImportance, OKFType
from tars.domains.proactive.delivery.base import DeliveryResult
from tars.domains.proactive.delivery.router import DeliveryRouter
from tars.domains.proactive.generator.prompts import build_proactive_prompt
from tars.domains.proactive.generator.schemas import GeneratorInput
from tars.domains.proactive.scanner.schemas import UtteranceCandidate
from tars.domains.proactive.schemas import ProactivePayload, ScheduleType
from tars.domains.proactive.scorer.engine import UtteranceThresholdScorer
from tars.domains.proactive.scorer.policy import (
    DefaultReviewCyclePolicy,
    ProactiveScorerPolicy,
)


@pytest.mark.unit
def test_default_review_cycle_policy() -> None:
    """Verify DefaultReviewCyclePolicy returns appropriate interval days."""
    policy = DefaultReviewCyclePolicy()

    assert policy.days_for(OKFType.CONCEPT, OKFImportance.CRITICAL) == 1
    assert policy.days_for(OKFType.CONCEPT, OKFImportance.HIGH) == 3
    assert policy.days_for(OKFType.CONCEPT, OKFImportance.MEDIUM) == 7
    assert policy.days_for(OKFType.CONCEPT, OKFImportance.LOW) == 14

    assert policy.days_for(OKFType.PROCEDURE, OKFImportance.MEDIUM) == 10
    assert policy.days_for(OKFType.RULE, OKFImportance.MEDIUM) == 14


@pytest.mark.unit
def test_utterance_threshold_scorer_activation() -> None:
    """Verify high-desire candidate successfully passes activation threshold."""
    scorer = UtteranceThresholdScorer(policy=ProactiveScorerPolicy(utterance_threshold=6.0))

    candidate = UtteranceCandidate(
        user_id="user_123",
        schedule_type=ScheduleType.REVIEW_REMINDER,
        okf_id="python-async",
        importance=OKFImportance.HIGH,
        elapsed_days=7.0,
        review_cycle_days=7,
        has_conversation_context=True,
    )

    verdict = scorer.evaluate(
        candidate=candidate,
        recent_send_count=0,
        hours_since_last_send=12.0,
    )

    assert verdict.is_above_threshold is True
    assert verdict.suppressed_reason is None
    assert verdict.final_score >= 6.0
    assert verdict.score_breakdown.fatigue_penalty == 0.0


@pytest.mark.unit
def test_utterance_threshold_scorer_suppressed_by_daily_limit() -> None:
    """Verify candidates are suppressed when max daily send limit is reached."""
    scorer = UtteranceThresholdScorer(
        policy=ProactiveScorerPolicy(utterance_threshold=5.0, max_daily_proactive=3)
    )

    candidate = UtteranceCandidate(
        user_id="user_123",
        schedule_type=ScheduleType.REVIEW_REMINDER,
        okf_id="python-async",
        importance=OKFImportance.CRITICAL,
        elapsed_days=10.0,
        review_cycle_days=7,
        has_conversation_context=True,
    )

    verdict = scorer.evaluate(
        candidate=candidate,
        recent_send_count=3,  # Reached ceiling
        hours_since_last_send=5.0,
    )

    assert verdict.is_above_threshold is False
    assert verdict.suppressed_reason == "daily_limit"


@pytest.mark.unit
def test_utterance_threshold_scorer_suppressed_by_silence_cooldown() -> None:
    """Verify candidates are suppressed within minimum silence interval."""
    scorer = UtteranceThresholdScorer(
        policy=ProactiveScorerPolicy(utterance_threshold=5.0, min_silence_hours=2)
    )

    candidate = UtteranceCandidate(
        user_id="user_123",
        schedule_type=ScheduleType.REVIEW_REMINDER,
        okf_id="python-async",
        importance=OKFImportance.HIGH,
        elapsed_days=8.0,
        review_cycle_days=7,
    )

    verdict = scorer.evaluate(
        candidate=candidate,
        recent_send_count=1,
        hours_since_last_send=0.8,  # Only 48 minutes elapsed
    )

    assert verdict.is_above_threshold is False
    assert verdict.suppressed_reason == "silence_cooldown"


@pytest.mark.unit
def test_build_proactive_prompt_layers() -> None:
    """Verify prompt builder creates a 5-layer prompt with Zero-Example constraints."""
    inp = GeneratorInput(
        user_id="user_123",
        persona_id="miu",
        schedule_type=ScheduleType.REVIEW_REMINDER,
        okf_document_summary="FastAPI 비동기 아키텍처 및 세션 수명주기 정리",
        okf_title="FastAPI Lifespan Guide",
        okf_importance=OKFImportance.HIGH,
        last_conversation_fragment="어제 백엔드 세션 처리 이야기 나눔",
        temporal_context="화요일 오전 10시 (KST)",
        elapsed_days=7.0,
        review_cycle_days=7,
        threshold_score=8.5,
    )

    prompt = build_proactive_prompt(inp)

    # 1. Check Layer headers
    assert "[SYSTEM DIRECTIVE PRIORITY]" in prompt
    assert "[CORE IDENTITY & PROACTIVE VOICE]" in prompt
    assert "[BEHAVIORAL DIRECTIVE - REVIEW REMINDER]" in prompt
    assert "[STRICT PROHIBITIONS]" in prompt
    assert "[DYNAMIC CONTEXT SLOTS]" in prompt

    # 2. Check context slots inclusion
    assert "FastAPI Lifespan Guide" in prompt
    assert "FastAPI 비동기 아키텍처" in prompt
    assert "화요일 오전 10시 (KST)" in prompt
    assert "마지막 확인 후 약 7일 경과" in prompt

    # 3. Check Zero-Example compliance: no quoted dialogue templates
    assert "예시:" not in prompt
    assert "Example:" not in prompt
    assert '"주인님, 안녕' not in prompt


@pytest.mark.asyncio
async def test_delivery_router_fallback_chain() -> None:
    """Verify DeliveryRouter tries WS, then FCM, and always persists to Inbox."""
    mock_ws = MagicMock()
    mock_ws.is_available = AsyncMock(return_value=False)

    mock_fcm = MagicMock()
    mock_fcm.is_available = AsyncMock(return_value=True)
    mock_fcm.send = AsyncMock(
        return_value=DeliveryResult(channel_name="fcm_push", success=True)
    )

    mock_inbox = MagicMock()
    mock_inbox.send = AsyncMock(
        return_value=DeliveryResult(channel_name="inbox_db", success=True)
    )

    router = DeliveryRouter(
        ws_channel=mock_ws,
        fcm_channel=mock_fcm,
        inbox_channel=mock_inbox,
    )

    payload = ProactivePayload(
        message_id="test_msg_id",
        persona_id="miu",
        schedule_type=ScheduleType.REVIEW_REMINDER,
        content="주인님, 복습할 시간입니다.",
        scheduled_at_utc="2026-09-22T07:00:00Z",
    )

    results = await router.deliver(user_id="user_123", payload=payload)

    # WS was not available so it shouldn't have been called for send
    mock_ws.send.assert_not_called()
    # FCM was available and sent
    mock_fcm.send.assert_awaited_once_with("user_123", payload)
    # Inbox was called unconditionally with delivered=True
    mock_inbox.send.assert_awaited_once_with("user_123", payload, delivered=True)

    assert len(results) == 2
    assert results[0].channel_name == "fcm_push"
    assert results[1].channel_name == "inbox_db"
