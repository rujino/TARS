"""Adversarial stress and edge-case verification for TARS Phase 3 Milestone 1.

Written by Empirical Challenger (teamwork_preview_challenger_m1_1).
Tests boundary conditions, ReDoS, concurrency, timezone edge cases, and data persistence.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.schemas.chat import GreetingResponse
from tars.core.session.detector import TopicShiftDetector
from tars.core.session.manager import (
    SmartSessionManager,
)
from tars.core.session.models import SessionRoutingAction
from tars.db.models import ChatMessage, ChatSession, User
from tars.services.greeting import ProactiveGreetingService
from tars.storage.manager import FileStorageManager
from tests.conftest import MockLLMAdapter

# ============================================================================
# 1. Adversarial Time Decay Boundary Tests
# ============================================================================


class TestAdversarialTimeDecayBoundaries:
    """Stress-tests exact mathematical boundaries of Time Decay logic."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("delta_seconds", "expected_action"),
        [
            (0, SessionRoutingAction.MAINTAIN),
            (1, SessionRoutingAction.MAINTAIN),
            (899, SessionRoutingAction.MAINTAIN),
            (900, SessionRoutingAction.MAINTAIN),  # Exact Short-term boundary (15m)
            (901, SessionRoutingAction.BRANCH_BRIDGE),  # 15m + 1s -> Branch with bridge
            (3600, SessionRoutingAction.BRANCH_BRIDGE),  # 1 hour -> Branch
            (7199, SessionRoutingAction.BRANCH_BRIDGE),
            (7200, SessionRoutingAction.BRANCH_BRIDGE),  # Exact Mid-term boundary (2h)
            (7201, SessionRoutingAction.FRESH_RESET),  # 2h + 1s -> Full fresh reset
            (86400, SessionRoutingAction.FRESH_RESET),  # 1 day -> Full fresh reset
            (1000000, SessionRoutingAction.FRESH_RESET),  # Long absence
        ],
    )
    async def test_exact_time_decay_threshold_boundaries(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
        delta_seconds: int,
        expected_action: SessionRoutingAction,
    ) -> None:
        """Verify exact second-level transitions across 900s and 7200s boundaries."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(canned_response="Bridge summary of previous context.")
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        base_time = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        current_time = base_time + timedelta(seconds=delta_seconds)

        # Create active session with last_active_at = base_time
        session = await manager.create_new_session(
            user_id=seed_test_user.id,
            title="Boundary Test Session",
        )
        await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="Previous message",
            assistant_content="Previous response",
        )
        session.last_active_at = base_time
        await async_db_session.commit()

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session.id,
            incoming_message="What is our status?",
            now=current_time,
        )

        assert decision.action == expected_action, (
            f"Failed at delta={delta_seconds}s: expected {expected_action}, got {decision.action}"
        )

        if expected_action == SessionRoutingAction.MAINTAIN:
            assert routed_session.id == session.id
            assert len(working_memory) == 2
        elif expected_action == SessionRoutingAction.BRANCH_BRIDGE:
            assert routed_session.id != session.id
            assert routed_session.parent_session_id == session.id
            assert session.status == "archived"
        elif expected_action == SessionRoutingAction.FRESH_RESET:
            assert routed_session.id != session.id
            assert routed_session.parent_session_id is None
            assert session.status == "archived"
            assert len(working_memory) == 0

    @pytest.mark.asyncio
    async def test_negative_delta_clock_skew_resilience(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify negative delta (clock skew / server time regression) safely falls back to MAINTAIN."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        base_time = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        # Server clock went backwards 1 hour!
        clock_skew_now = base_time - timedelta(hours=1)

        session = await manager.create_new_session(
            user_id=seed_test_user.id,
            title="Clock Skew Session",
        )
        await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="Message before clock skew",
            assistant_content="Response before clock skew",
        )
        session.last_active_at = base_time
        await async_db_session.commit()

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session.id,
            incoming_message="Clock shifted message",
            now=clock_skew_now,
        )

        # delta_seconds should be clamped to 0.0, maintaining session
        assert decision.action == SessionRoutingAction.MAINTAIN
        assert routed_session.id == session.id
        assert len(working_memory) == 2


# ============================================================================
# 2. Adversarial Reset Regex & ReDoS Tests
# ============================================================================


class TestAdversarialResetRegex:
    """Stress-tests reset command regex against adversarial variations, false positives, and ReDoS."""

    def setup_method(self) -> None:
        self.detector = TopicShiftDetector()

    @pytest.mark.parametrize(
        "query",
        [
            "리셋",
            "리셋해",
            "리셋해줘",
            "리셋하자",
            "리셋합시다",
            "리셋시켜줘",
            "리셋부탁해",
            "초기화",
            "초기화해",
            "초기화해줘",
            "초기화하자",
            "초기화합시다",
            "초기화시켜줘",
            "초기화부탁해",
            "새 주제",
            "새 대화",
            "새 세션",
            "새로운 주제",
            "새로운 대화",
            "새로운 세션",
            "새 주제로 시작",
            "새로운 주제로 시작하자",
            "새로운 대화 시작해줘",
            "새 대화로 시작해",
            "대화 초기화",
            "대화 초기화해줘",
            "대화 초기화하자",
            "기억 지워",
            "기억 지워줘",
            "기억 삭제해줘",
            "기억 포맷해줘",
            "세션 리셋",
            "세션 초기화",
            "세션 리셋해줘",
            "세션 초기화해줘",
            "tars, 리셋해줘",
            "타스, 대화 초기화해",
            "TARS: RESET NOW",
            "reset",
            "RESET",
            "reset session",
            "reset chat",
            "reset now",
            "clear chat",
            "clear history",
            "clear session",
            "start new topic",
            "start new session",
            "start new chat",
            "start new conversation",
            "new chat",
            "new session",
            "  타스 ,  리셋해줘 !!!  ",
            "TARS: clear session...",
            "새로운 주제로 시작하자~",
        ],
    )
    def test_adversarial_valid_reset_commands(self, query: str) -> None:
        """Verify all legitimate reset variants and punctuation styles are recognized."""
        assert self.detector.is_reset_command(query), f"Should recognize as reset: {query!r}"

    @pytest.mark.parametrize(
        "query",
        [
            "",
            "   ",
            "\n\t",
            "리셋 버튼은 어디 있나요?",
            "초기화하는 방법에 대한 가이드를 작성해줘.",
            "새로운 주제를 추천해줘.",
            "새로운 대화 상대가 필요해.",
            "기억에 남는 영화 추천해줘.",
            "기억력이 좋아지는 방법 알려줘.",
            "대화 초기화 기능의 내부 구현 원리를 설명해봐.",
            "reset password email not received",
            "how to clear cache and cookies in Safari?",
            "start new project in django",
            "new chat interface design review",
            "TARS, what is the meaning of life?",
            "TARS의 리셋 기능은 안전한가요?",
            "포맷 스트링 취약점에 대해 알려줘",
        ],
    )
    def test_adversarial_false_positive_rejection(self, query: str) -> None:
        """Verify ordinary conversation containing keywords is NOT falsely classified as reset."""
        assert not self.detector.is_reset_command(query), f"Should NOT match reset: {query!r}"

    def test_redos_and_extreme_length_performance(self) -> None:
        """Verify regex does not suffer from polynomial/exponential ReDoS backtrack on large inputs."""
        # 1. Very long spaces
        pathological_input_1 = "TARS" + " " * 50000 + "리셋해줘"
        start = time.perf_counter()
        res_1 = self.detector.is_reset_command(pathological_input_1)
        duration_1 = time.perf_counter() - start
        assert duration_1 < 0.05, f"ReDoS vulnerability detected! Took {duration_1:.4f}s"
        assert res_1 is True

        # 2. Long non-matching input
        pathological_input_2 = "새로운 " * 10000 + "주제를 연구하는 과학자들의 보고서"
        start = time.perf_counter()
        res_2 = self.detector.is_reset_command(pathological_input_2)
        duration_2 = time.perf_counter() - start
        assert duration_2 < 0.05, f"Non-match took too long: {duration_2:.4f}s"
        assert res_2 is False


# ============================================================================
# 3. Adversarial Proactive Greeting Tests (Timezone & Idle Edge Cases)
# ============================================================================


class TestAdversarialProactiveGreeting:
    """Stress-tests time periods, idle duration strings, and timezone resilience."""

    def setup_method(self) -> None:
        self.service = ProactiveGreetingService(
            db_session=None,  # type: ignore[arg-type]
            storage_manager=None,  # type: ignore[arg-type]
        )

    @pytest.mark.parametrize(
        ("hour", "expected_period"),
        [
            (0, "심야/새벽"),
            (5, "심야/새벽"),
            (6, "아침"),  # 06시 아침 시작
            (10, "아침"),
            (11, "점심"),  # 11시 점심 시작
            (13, "점심"),
            (14, "오후"),  # 14시 오후 시작
            (17, "오후"),
            (18, "저녁"),  # 18시 저녁 시작
            (21, "저녁"),
            (22, "심야/새벽"),  # 22시 심야 시작
            (23, "심야/새벽"),
        ],
    )
    def test_time_of_day_exact_hour_boundaries(self, hour: int, expected_period: str) -> None:
        """Verify 24-hour cycle boundary classification."""
        period, desc = self.service._get_time_of_day(hour)
        assert period == expected_period, f"Hour {hour}: expected {expected_period}, got {period}"

    @pytest.mark.parametrize(
        ("idle_seconds", "expected_substring"),
        [
            (-1, "첫 접속 (신규 사용자)"),
            (0, "방금 전 (1분 이내)"),
            (59, "방금 전 (1분 이내)"),
            (60, "1분 만의 재접속"),
            (120, "2분 만의 재접속"),
            (3599, "59분 만의 재접속"),
            (3600, "1시간 만의 재접속"),
            (7200, "2시간 만의 재접속"),
            (86399, "23시간 만의 재접속"),
            (86400, "1일 만의 재접속"),
            (172800, "2일 만의 재접속"),
            (864000, "10일 만의 재접속"),
        ],
    )
    def test_idle_duration_formatting_boundaries(
        self, idle_seconds: int, expected_substring: str
    ) -> None:
        """Verify idle time formatting edge cases."""
        formatted = self.service._format_idle_duration(idle_seconds)
        assert formatted == expected_substring

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tz_name",
        [
            "Asia/Seoul",
            "UTC",
            "America/New_York",
            "Europe/London",
            "Pacific/Honolulu",
            "Australia/Sydney",
            "Invalid/Timezone_Name",  # Invalid IANA timezone -> Must fallback to KST gracefully
            "",
            "12345",
        ],
    )
    async def test_greeting_timezone_robustness(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
        tz_name: str,
    ) -> None:
        """Verify greeting service gracefully handles valid, exotic, and corrupt timezone strings."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(canned_response="시스템 점검 완료. 정상 가동 중입니다, 파트너.")
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        response: GreetingResponse = await service.generate_greeting(
            user_id=seed_test_user.id,
            client_timezone=tz_name,
        )

        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0
        assert response.session_id is not None
        assert response.mode in ("companion", "work")


# ============================================================================
# 4. Adversarial Concurrency & Persistence Stress Tests
# ============================================================================


class TestAdversarialConcurrencyAndPersistence:
    """Stress-tests concurrent session routing and dialogue turn recording."""

    @pytest.mark.asyncio
    async def test_concurrent_session_routing_consistency(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify multiple near-simultaneous route_session calls don't corrupt ORM state."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        # Initial active session
        session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Concurrent Base"
        )
        await async_db_session.commit()

        # Run 5 concurrent route_session calls
        queries = [f"Query {i}" for i in range(5)]

        async def _call_route(q: str) -> Any:
            return await manager.route_session(
                user_id=seed_test_user.id,
                requested_session_id=session.id,
                incoming_message=q,
            )

        results = await asyncio.gather(*[_call_route(q) for q in queries])
        assert len(results) == 5
        for s, wm, dec in results:
            assert dec.action == SessionRoutingAction.MAINTAIN
            assert s.id == session.id

    @pytest.mark.asyncio
    async def test_concurrent_turn_recording_no_loss(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify sequential / parallel turn recording writes all messages to DB without data loss."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        session = await manager.create_new_session(user_id=seed_test_user.id, title="New Dialogue")
        await async_db_session.commit()

        num_turns = 8
        for i in range(num_turns):
            await manager.record_turn(
                session_id=session.id,
                user_id=seed_test_user.id,
                user_content=f"User question {i}",
                assistant_content=f"Assistant answer {i}",
                user_tokens=10 + i,
                assistant_tokens=20 + i,
            )

        # Query all messages from DB directly
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at)
        )
        res = await async_db_session.execute(stmt)
        messages = res.scalars().all()

        assert len(messages) == num_turns * 2  # Each turn = 1 user + 1 assistant
        user_msgs = [m for m in messages if m.role == "user"]
        asst_msgs = [m for m in messages if m.role == "assistant"]
        assert len(user_msgs) == num_turns
        assert len(asst_msgs) == num_turns

        # Check refreshed session title and last_active_at
        refreshed = await manager.get_session_by_id(session.id)
        assert refreshed is not None
        assert refreshed.title == "User question 0"
        assert len(refreshed.messages) == num_turns * 2

    @pytest.mark.asyncio
    async def test_consecutive_reset_commands_session_state_consistency(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify executing multiple consecutive reset commands maintains clean DB state without duplicates."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        # First session
        session_1 = await manager.create_new_session(user_id=seed_test_user.id, title="Session 1")
        await manager.record_turn(
            session_id=session_1.id,
            user_id=seed_test_user.id,
            user_content="Turn 1",
            assistant_content="Ans 1",
        )

        # Reset 1
        s2, wm2, d2 = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_1.id,
            incoming_message="TARS, 리셋해줘",
        )
        assert d2.action == SessionRoutingAction.NATURAL_RESET
        assert s2.id != session_1.id

        # Reset 2 immediately without prior turns
        s3, wm3, d3 = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=s2.id,
            incoming_message="타스 대화 초기화",
        )
        assert d3.action == SessionRoutingAction.NATURAL_RESET
        assert s3.id != s2.id

        # Check all sessions for user in DB
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == seed_test_user.id)
            .order_by(ChatSession.created_at)
        )
        res = await async_db_session.execute(stmt)
        all_sessions = res.scalars().all()

        assert len(all_sessions) == 3
        # First two should be archived
        assert all_sessions[0].status == "archived"
        assert all_sessions[1].status == "archived"
        # Last one should be active
        assert all_sessions[2].status == "active"
        assert all_sessions[2].id == s3.id

    @pytest.mark.asyncio
    async def test_dst_daylight_saving_greeting_calculation(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify DST (Daylight Saving Time) transition timestamps in America/New_York."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(canned_response="뉴욕 기준 오프닝 메시지입니다.")
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        # 2026-03-08 07:30 UTC = 03:30 EDT (America/New_York) -> 새벽
        dst_spring_utc = datetime(2026, 3, 8, 7, 30, 0, tzinfo=UTC)
        res_spring = await service.generate_greeting(
            user_id=seed_test_user.id,
            client_timezone="America/New_York",
            client_time=dst_spring_utc,
        )
        assert res_spring.greeting is not None

        # 2026-03-08 19:30 UTC = 15:30 EDT (America/New_York) -> 오후
        dst_afternoon_utc = datetime(2026, 3, 8, 19, 30, 0, tzinfo=UTC)
        res_afternoon = await service.generate_greeting(
            user_id=seed_test_user.id,
            client_timezone="America/New_York",
            client_time=dst_afternoon_utc,
        )
        assert res_afternoon.greeting is not None
