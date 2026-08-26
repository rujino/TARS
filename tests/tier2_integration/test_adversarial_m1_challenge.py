"""Tier 2 Adversarial Empirical Challenge Suite for Milestone 1.

Stress-tests:
1. Proactive Greeting 5-Factor Combinations:
   - Empty context & zero knowledge (new user, 0 sessions, 0 OKF wikis)
   - Invalid and pathological timezones ("Invalid/Timezone", "Mars/Olympus", "", "UTC+99")
   - Boundary hours (all 24 hours, midnight, morning, afternoon, evening, dawn)
   - Extreme persona combinations (0.0/0.0, 1.0/1.0, work vs companion)
   - LLM failure/timeout fallback safety
2. Topic Shift Rapid Consecutive Switching & Boundary Stress:
   - 5+ consecutive rapid topic shifts with lineage & memory isolation verification
   - Pathological inputs (empty, whitespace, huge text, single char, malformed JSON, timeout)
3. Session Archiving Async Background Task Fault Isolation:
   - LLM crash, DB error, storage error inside _run_async_knowledge_extraction
   - Verification that background task failure never impacts main session routing or client streaming
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.router import HybridLLMRouter
from tars.api.schemas.chat import GreetingResponse
from tars.core.session.detector import TopicShiftDetector
from tars.core.session.manager import (
    SmartSessionManager,
    _run_async_knowledge_extraction,
)
from tars.core.session.models import SessionRoutingAction
from tars.db.models import ChatSession, TARSSettings, User
from tars.persona.prompts import (
    build_greeting_prompt,
    build_tars_system_prompt,
)
from tars.services.greeting import ProactiveGreetingService
from tars.storage.manager import FileStorageManager
from tests.conftest import MockLLMAdapter

# ============================================================================
# 1. Proactive Greeting 5-Factor Adversarial Tests
# ============================================================================


class TestProactiveGreetingAdversarial:
    """Adversarial stress-testing of Proactive Greeting service."""

    @pytest.mark.asyncio
    async def test_greeting_empty_context_and_zero_knowledge(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify greeting handles brand new user with 0 sessions and 0 OKF wikis without failure."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(
            canned_response="첫 접속을 환영합니다, 파트너. TARS 가동 준비 완료."
        )
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        response: GreetingResponse = await service.generate_greeting(
            user_id=seed_test_user.id,
            client_timezone="Asia/Seoul",
        )

        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0
        assert response.idle_seconds == 0  # max(0, -1) -> 0
        assert response.session_id is not None
        assert response.mode == "companion"

        # Verify a fresh active session was automatically created in DB
        stmt = select(ChatSession).where(ChatSession.id == response.session_id)
        res = await async_db_session.execute(stmt)
        session = res.scalar_one_or_none()
        assert session is not None
        assert session.status == "active"
        assert session.user_id == seed_test_user.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_tz",
        [
            "Invalid/Timezone",
            "Mars/Olympus_Mons",
            "KST-99",
            "",
            "   ",
            "../../../../etc/passwd",
            "None",
            "UTC+100",
        ],
    )
    async def test_greeting_pathological_timezones_fallback_safely(
        self,
        invalid_tz: str,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify invalid or adversarial timezone strings fall back safely to default KST (UTC+9)."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=None,  # test fallback generator
        )

        response = await service.generate_greeting(
            user_id=seed_test_user.id,
            client_timezone=invalid_tz,
        )
        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0
        assert response.session_id is not None

    @pytest.mark.asyncio
    async def test_greeting_24_hour_boundary_coverage(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify _get_time_of_day and fallback generation across all 24 hours of the day."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=None,
        )

        expected_categories = {
            0: "심야/새벽",
            5: "심야/새벽",
            6: "아침",
            10: "아침",
            11: "점심",
            13: "점심",
            14: "오후",
            17: "오후",
            18: "저녁",
            21: "저녁",
            22: "심야/새벽",
            23: "심야/새벽",
        }

        for hour, expected_cat in expected_categories.items():
            category, formatted = service._get_time_of_day(hour)
            assert category == expected_cat, f"Hour {hour}: expected {expected_cat}, got {category}"
            assert f"{hour}" in formatted or f"{hour - 12}" in formatted

            # Test prompt building for each hour
            prompt = build_greeting_prompt(
                time_of_day_str=category,
                current_time_str=f"2026-08-26 {hour:02d}:00",
                idle_duration_str="1시간 만의 재접속",
            )
            assert category in prompt

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("humor", "honesty", "mode"),
        [
            (0.0, 0.0, "work"),
            (1.0, 1.0, "companion"),
            (0.0, 1.0, "companion"),
            (1.0, 0.0, "work"),
            (0.5, 0.5, "companion"),
        ],
    )
    async def test_greeting_extreme_persona_combinations(
        self,
        humor: float,
        honesty: float,
        mode: str,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify extreme persona parameter combinations generate valid prompts and fallback greetings."""
        # Update user settings in DB
        stmt = select(TARSSettings).where(TARSSettings.user_id == seed_test_user.id)
        res = await async_db_session.execute(stmt)
        settings = res.scalar_one()
        settings.humor_level = humor
        settings.honesty_level = honesty
        settings.mode = mode
        await async_db_session.commit()

        storage = FileStorageManager(base_dir=temp_storage_root)
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=None,  # Fallback engine
        )

        response = await service.generate_greeting(user_id=seed_test_user.id)
        assert isinstance(response, GreetingResponse)
        assert response.mode == mode
        assert len(response.greeting) > 0

        # Verify prompt builder with extreme parameters
        prompt = build_tars_system_prompt(humor_level=humor, honesty_level=honesty, mode=mode)
        assert str(int(humor * 100)) in prompt
        assert str(int(honesty * 100)) in prompt

    @pytest.mark.asyncio
    async def test_greeting_llm_failure_and_empty_response_fallback(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify that when LLM throws an exception or returns empty string, fallback greeting is smoothly returned."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        failing_llm = MockLLMAdapter(should_fail=True)

        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=failing_llm,
        )

        response = await service.generate_greeting(user_id=seed_test_user.id)
        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0
        assert (
            "TARS" in response.greeting
            or "파트너" in response.greeting
            or "시스템" in response.greeting
        )


# ============================================================================
# 2. Topic Shift Rapid Consecutive Switching & Boundary Stress
# ============================================================================


class TestTopicShiftRapidConsecutiveStress:
    """Stress-testing consecutive topic shifts, session lineage, and working memory isolation."""

    @pytest.mark.asyncio
    async def test_consecutive_rapid_topic_shifts_chain(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Execute a chain of 5+ rapid topic shifts and verify session tree, titles, and message isolation."""
        storage = FileStorageManager(base_dir=temp_storage_root)

        # Dynamic mock LLM returning topic shifts based on query keyword
        class TopicShiftingLLM(MockLLMAdapter):
            async def agenerate(self, messages: Any, system_prompt: str = "", **kwargs: Any) -> str:
                prompt_text = str(messages[0].content) if messages else ""
                query_part = prompt_text
                if "[INCOMING QUERY]" in prompt_text:
                    query_part = prompt_text.split("[INCOMING QUERY]")[1]

                if "요리" in query_part or "파스타" in query_part:
                    return '{"is_topic_shift": true, "new_topic": "이탈리안 요리"}'
                if "주식" in query_part or "투자" in query_part:
                    return '{"is_topic_shift": true, "new_topic": "주식 투자 전략"}'
                if "화성" in query_part or "우주" in query_part:
                    return '{"is_topic_shift": true, "new_topic": "화성 테라포밍"}'
                return '{"is_topic_shift": false, "new_topic": null}'

        llm = TopicShiftingLLM()
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=llm,
        )

        now = datetime.now(UTC)

        # --- Turn 1: Initial Session A (Quantum) ---
        session_a, mem_a, dec_a = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=None,
            incoming_message="양자 역학의 불확정성 원리를 설명해줘.",
            now=now,
        )
        assert dec_a.action == SessionRoutingAction.FRESH_RESET
        await manager.record_turn(
            session_id=session_a.id,
            user_id=seed_test_user.id,
            user_content="양자 역학의 불확정성 원리를 설명해줘.",
            assistant_content="입자의 위치와 운동량을 동시에 정확히 측정할 수 없습니다.",
        )

        # --- Turn 2: Follow-up on Quantum (Maintain Session A) ---
        session_a2, mem_a2, dec_a2 = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_a.id,
            incoming_message="그럼 파동 함수 붕괴는 어떻게 일어나지?",
            now=now + timedelta(minutes=2),
        )
        assert dec_a2.action == SessionRoutingAction.MAINTAIN
        assert session_a2.id == session_a.id
        assert len(mem_a2) == 2  # 1 previous turn (2 messages)
        await manager.record_turn(
            session_id=session_a2.id,
            user_id=seed_test_user.id,
            user_content="그럼 파동 함수 붕괴는 어떻게 일어나지?",
            assistant_content="관측 행위를 통해 중첩 상태가 하나의 고유 상태로 수렴합니다.",
        )

        # --- Turn 3: Abrupt Topic Shift to Cooking -> Branched to Session B ---
        session_b, mem_b, dec_b = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_a.id,
            incoming_message="오늘 저녁으로 알리오 올리오 파스타 만드는 법 알려줘.",
            now=now + timedelta(minutes=4),
        )
        assert dec_b.action == SessionRoutingAction.TOPIC_SHIFT
        assert session_b.id != session_a.id
        assert session_b.parent_session_id == session_a.id
        assert session_b.title == "이탈리안 요리"
        assert len(mem_b) == 0  # Working memory is freshly isolated!
        await manager.record_turn(
            session_id=session_b.id,
            user_id=seed_test_user.id,
            user_content="오늘 저녁으로 알리오 올리오 파스타 만드는 법 알려줘.",
            assistant_content="올리브유에 마늘과 페페론치노를 볶은 후 면수를 넣고 만티카레합니다.",
        )

        # --- Turn 4: Abrupt Topic Shift to Stock Trading -> Branched to Session C ---
        session_c, mem_c, dec_c = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_b.id,
            incoming_message="미국 기술주 주식 포트폴리오 비중을 어떻게 조절해야 할까?",
            now=now + timedelta(minutes=6),
        )
        assert dec_c.action == SessionRoutingAction.TOPIC_SHIFT
        assert session_c.id != session_b.id
        assert session_c.parent_session_id == session_b.id
        assert session_c.title == "주식 투자 전략"
        assert len(mem_c) == 0
        await manager.record_turn(
            session_id=session_c.id,
            user_id=seed_test_user.id,
            user_content="미국 기술주 주식 포트폴리오 비중을 어떻게 조절해야 할까?",
            assistant_content="거시경제 변동성을 고려하여 분할 매수와 현금 비중 20%를 권장합니다.",
        )

        # --- Turn 5: Natural Reset Command -> Fresh Session D ---
        session_d, mem_d, dec_d = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_c.id,
            incoming_message="TARS, 세션 초기화해줘",
            now=now + timedelta(minutes=8),
        )
        assert dec_d.action == SessionRoutingAction.NATURAL_RESET
        assert dec_d.is_reset is True
        assert session_d.id != session_c.id
        assert session_d.parent_session_id is None
        assert len(mem_d) == 0

        # --- Turn 6: Start Space Exploration in Session D ---
        session_d2, mem_d2, dec_d2 = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session_d.id,
            incoming_message="화성 기지 건설 계획을 수립해보자.",
            now=now + timedelta(minutes=9),
        )
        assert dec_d2.action == SessionRoutingAction.MAINTAIN
        assert session_d2.id == session_d.id
        await manager.record_turn(
            session_id=session_d2.id,
            user_id=seed_test_user.id,
            user_content="화성 기지 건설 계획을 수립해보자.",
            assistant_content="1단계 거주 모듈 설치와 인시튜(ISRU) 산소 생성이 선행되어야 합니다.",
        )

        # Verify DB Statuses and History Integrity
        reload_a = await manager.get_session_by_id(session_a.id)
        reload_b = await manager.get_session_by_id(session_b.id)
        reload_c = await manager.get_session_by_id(session_c.id)
        reload_d = await manager.get_session_by_id(session_d.id)

        assert reload_a is not None and reload_a.status == "archived"
        assert reload_b is not None and reload_b.status == "archived"
        assert reload_c is not None and reload_c.status == "archived"
        assert reload_d is not None and reload_d.status == "active"

        # Verify Message Counts per Session
        assert len(reload_a.messages) == 4  # 2 turns
        assert len(reload_b.messages) == 2  # 1 turn
        assert len(reload_c.messages) == 2  # 1 turn
        assert len(reload_d.messages) == 2  # 1 turn

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "adversarial_query",
        [
            "",
            "   ",
            "\n\t\r",
            "?",
            "!",
            ".",
            "a",
            "X" * 10000,  # 10k long string
            "```json\n{'invalid': true}\n```",
            "<script>alert(1)</script>",
        ],
    )
    async def test_topic_shift_detector_adversarial_inputs(
        self,
        adversarial_query: str,
    ) -> None:
        """Verify TopicShiftDetector handles pathological, boundary, and malformed inputs gracefully without crashing."""
        mock_llm = MockLLMAdapter(canned_response="Malformed non-json output from LLM")
        detector = TopicShiftDetector(llm_adapter=mock_llm)

        history = [
            HumanMessage(content="Previous context turn"),
            AIMessage(content="Previous response turn"),
        ]

        # Should never raise Exception, returns safe TopicShiftResult(is_topic_shift=False)
        result = await detector.detect_topic_shift(
            recent_turns=history,
            new_query=adversarial_query,
        )
        assert result.is_topic_shift is False

    @pytest.mark.asyncio
    async def test_topic_shift_detector_json_markdown_fence_cleaning(self) -> None:
        """Verify detector properly cleans markdown json fences returned by LLMs."""
        fenced_json = (
            '```json\n{\n  "is_topic_shift": true,\n  "new_topic": "Neural Networks"\n}\n```'
        )
        mock_llm = MockLLMAdapter(canned_response=fenced_json)
        detector = TopicShiftDetector(llm_adapter=mock_llm)

        history = [
            HumanMessage(content="What is a gradient?"),
            AIMessage(content="A gradient is a vector of partial derivatives."),
        ]
        result = await detector.detect_topic_shift(
            recent_turns=history,
            new_query="How do transformers use self-attention?",
        )
        assert result.is_topic_shift is True
        assert result.new_topic == "Neural Networks"


# ============================================================================
# 3. Session Archiving & Async Background Task Isolation Tests
# ============================================================================


class TestSessionArchivingAsyncIsolation:
    """Stress-testing background knowledge extraction error isolation and system resilience."""

    @pytest.mark.asyncio
    async def test_background_knowledge_extraction_llm_crash_isolated(
        self,
        temp_storage_root: Any,
    ) -> None:
        """Verify _run_async_knowledge_extraction catches LLM errors and does not crash process."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        crashing_llm = MockLLMAdapter(should_fail=True)

        messages = [
            HumanMessage(content="My favorite language is Python and I prefer dark mode."),
            AIMessage(content="Acknowledged. Preference noted."),
        ]

        # Calling directly should catch and log exception without raising
        await _run_async_knowledge_extraction(
            user_id="user_test_alpha",
            messages=messages,
            storage_manager=storage,
            extractor_llm=crashing_llm,
        )

    @pytest.mark.asyncio
    async def test_background_knowledge_extraction_handles_empty_turns(
        self,
        temp_storage_root: Any,
    ) -> None:
        """Verify _run_async_knowledge_extraction returns early when fewer than 2 turns are provided."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter()

        # Empty list
        await _run_async_knowledge_extraction(
            user_id="user_test_alpha",
            messages=[],
            storage_manager=storage,
            extractor_llm=mock_llm,
        )

        # Single message
        await _run_async_knowledge_extraction(
            user_id="user_test_alpha",
            messages=[HumanMessage(content="Single message")],
            storage_manager=storage,
            extractor_llm=mock_llm,
        )
        # Verify no calls were made to LLM
        assert len(mock_llm.call_history) == 0

    @pytest.mark.asyncio
    async def test_route_session_with_failing_background_tasks_isolation(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify route_session archives old session and dispatches to background tasks safely even on mid-term decay."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        failing_llm = MockLLMAdapter(should_fail=True)

        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=failing_llm,
        )

        now = datetime.now(UTC)
        # Create old session 30 minutes ago
        old_session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Old Mission"
        )
        await manager.record_turn(
            session_id=old_session.id,
            user_id=seed_test_user.id,
            user_content="Previous question",
            assistant_content="Previous answer",
        )
        old_session.last_active_at = now - timedelta(minutes=30)
        await async_db_session.commit()

        bg_tasks = BackgroundTasks()

        # Route session with mid-term decay and failing LLM
        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=old_session.id,
            incoming_message="New question after 30 minutes.",
            background_tasks=bg_tasks,
            now=now,
        )

        assert decision.action == SessionRoutingAction.BRANCH_BRIDGE
        assert routed_session.id != old_session.id
        assert old_session.status == "archived"
        assert len(bg_tasks.tasks) == 1

        # Execute scheduled background task to ensure it runs without raising
        task = bg_tasks.tasks[0]
        await task()


# ============================================================================
# 4. End-to-End API Integration & Extreme Load Simulation
# ============================================================================


class TestE2EAdversarialAPILoad:
    """E2E API stress testing over HTTP AsyncClient."""

    @pytest.mark.asyncio
    async def test_e2e_greeting_concurrent_requests(
        self,
        auth_client: AsyncClient,
        seed_test_user: User,
    ) -> None:
        """Simulate concurrent greeting requests and ensure session consistency."""
        with patch.object(
            HybridLLMRouter,
            "route_and_generate",
            return_value="시스템 진단 완료. 대기 중입니다, 파트너.",
        ):
            # Fire 10 concurrent greeting requests
            tasks = [
                auth_client.get("/api/v1/chat/greeting?timezone=Asia/Seoul") for _ in range(10)
            ]
            responses = await asyncio.gather(*tasks)

            for res in responses:
                assert res.status_code == 200
                data = res.json()
                assert "greeting" in data
                assert "session_id" in data
                assert data["mode"] == "companion"

    @pytest.mark.asyncio
    async def test_e2e_sse_stream_topic_shift_and_reset_sequence(
        self,
        auth_client: AsyncClient,
        async_db_session: AsyncSession,
        seed_test_user: User,
    ) -> None:
        """Test full SSE streaming endpoint through consecutive turns with topic shift and reset."""
        mock_tokens = ["TARS: ", "Operation ", "acknowledged."]

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            for t in mock_tokens:
                yield t

        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            # Turn 1: Normal message
            r1 = await auth_client.post(
                "/api/v1/chat/stream",
                json={"session_id": "default_session", "message": "First query."},
            )
            assert r1.status_code == 200
            assert "stream_start" in r1.text
            assert "stream_end" in r1.text

            # Turn 2: Reset message
            r2 = await auth_client.post(
                "/api/v1/chat/stream",
                json={"session_id": "default_session", "message": "새로운 주제로 시작하자"},
            )
            assert r2.status_code == 200
            assert "초기화" in r2.text or "신규" in r2.text or "아카이브" in r2.text
            assert "stream_end" in r2.text
