"""Tier 1 Unit Tests: Smart Session Manager, Topic Shift Detector, and Time Decay Lifecycle.

Verifies:
1. TopicShiftDetector:
   - Natural language reset command regex matching (Korean & English).
   - Non-reset conversation filtering.
   - Semantic topic shift LLM evaluation, fallback on timeout and errors.
2. SmartSessionManager Time Decay 3-Stage Routing:
   - Stage 1 (<= 15 mins): Session maintained with working memory history.
   - Stage 2 (15 mins ~ 2 hours): Bridge summary generation, session branching, old session archiving.
   - Stage 3 (> 2 hours): Fresh session initialization with empty working memory, old session archiving.
3. Natural Language Reset Lifecycle:
   - Immediate session archiving, fresh session creation, is_reset flag.
4. Semantic Topic Shift Routing:
   - Session branching upon topic change with parent linkage.
5. Dialogue Persistence (record_turn):
   - Atomically records user and assistant ChatMessage entries.
   - Updates session last_active_at timestamp.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.session.detector import TopicShiftDetector
from tars.core.session.manager import (
    SmartSessionManager,
)
from tars.core.session.models import SessionRoutingAction
from tars.db.models import User
from tars.storage.manager import FileStorageManager
from tests.conftest import MockLLMAdapter

# ============================================================================
# 1. TopicShiftDetector Unit Tests
# ============================================================================


class TestTopicShiftDetector:
    """Unit tests for regex reset command parsing and LLM topic shift classification."""

    def test_reset_command_regex_matches_korean(self) -> None:
        detector = TopicShiftDetector()
        valid_korean_resets = [
            "리셋",
            "리셋해",
            "리셋해줘",
            "TARS, 리셋해줘",
            "tars 리셋",
            "타스, 대화 초기화해",
            "초기화",
            "초기화해",
            "초기화해줘",
            "새 주제",
            "새로운 주제로 시작하자",
            "새로운 대화 시작해줘",
            "새 대화",
            "기억 지워",
            "기억 지워줘",
            "세션 리셋",
            "세션 초기화해줘",
            "TARS, 세션 리셋해.",
        ]
        for phrase in valid_korean_resets:
            assert detector.is_reset_command(phrase), f"Failed to match Korean reset: {phrase}"

    def test_reset_command_regex_matches_english(self) -> None:
        detector = TopicShiftDetector()
        valid_english_resets = [
            "reset",
            "RESET",
            "tars, reset",
            "TARS: reset now",
            "clear chat",
            "clear session",
            "start new session",
            "start new topic",
            "new chat",
            "new session",
            "TARS, clear history.",
        ]
        for phrase in valid_english_resets:
            assert detector.is_reset_command(phrase), f"Failed to match English reset: {phrase}"

    def test_reset_command_regex_rejects_regular_queries(self) -> None:
        detector = TopicShiftDetector()
        regular_queries = [
            "TARS, 블랙홀의 사건의 지평선에 대해 설명해줘.",
            "리셋 버튼은 어디에 있나요?",
            "새로운 프로젝트 계획을 작성해줘.",
            "오늘 서울의 날씨는 어때?",
            "What is the theory of relativity?",
            "Tell me a joke, TARS.",
        ]
        for query in regular_queries:
            assert not detector.is_reset_command(query), (
                f"Incorrectly matched regular query: {query}"
            )

    @pytest.mark.asyncio
    async def test_detect_topic_shift_with_insufficient_turns(self) -> None:
        detector = TopicShiftDetector()
        # Fewer than 2 turns
        single_msg = [HumanMessage(content="Hello")]
        result = await detector.detect_topic_shift(single_msg, "What is quantum mechanics?")
        assert not result.is_topic_shift
        assert result.new_topic is None

    @pytest.mark.asyncio
    async def test_detect_topic_shift_positive_classification(self) -> None:
        mock_llm = MockLLMAdapter(
            canned_response='{"is_topic_shift": true, "new_topic": "Quantum Computing"}'
        )
        detector = TopicShiftDetector(llm_adapter=mock_llm)

        history = [
            HumanMessage(content="Explain carbon capture technology."),
            AIMessage(content="Carbon capture absorbs CO2 from the atmosphere."),
        ]
        result = await detector.detect_topic_shift(
            history, "Let's code a quantum circuit in Qiskit."
        )
        assert result.is_topic_shift
        assert result.new_topic == "Quantum Computing"

    @pytest.mark.asyncio
    async def test_detect_topic_shift_negative_classification(self) -> None:
        mock_llm = MockLLMAdapter(canned_response='{"is_topic_shift": false, "new_topic": null}')
        detector = TopicShiftDetector(llm_adapter=mock_llm)

        history = [
            HumanMessage(content="What is Python's asyncio module?"),
            AIMessage(content="asyncio provides event loop concurrency in Python."),
        ]
        result = await detector.detect_topic_shift(
            history, "How does asyncio.gather differ from TaskGroup?"
        )
        assert not result.is_topic_shift

    @pytest.mark.asyncio
    async def test_detect_topic_shift_fallback_on_timeout(self) -> None:
        class HangingLLM(MockLLMAdapter):
            async def agenerate(self, *args: Any, **kwargs: Any) -> str:
                await asyncio.sleep(2.0)
                return '{"is_topic_shift": true}'

        detector = TopicShiftDetector(llm_adapter=HangingLLM())
        history = [
            HumanMessage(content="Query 1"),
            AIMessage(content="Response 1"),
        ]
        result = await detector.detect_topic_shift(history, "Query 2", timeout_seconds=0.05)
        # Should gracefully timeout and return False
        assert not result.is_topic_shift

    @pytest.mark.asyncio
    async def test_detect_topic_shift_default_timeout_is_2s(self) -> None:
        """Verify default timeout_seconds is 2.0s and allows realistic LLM latency (REL-05)."""
        import inspect

        sig = inspect.signature(TopicShiftDetector.detect_topic_shift)
        assert sig.parameters["timeout_seconds"].default == 2.0

        class RealisticCloudLLM(MockLLMAdapter):
            async def agenerate(self, *args: Any, **kwargs: Any) -> str:
                await asyncio.sleep(0.1)  # Realistic latency > 0.05s, within 2.0s
                return '{"is_topic_shift": true, "new_topic": "Stellar Evolution"}'

        detector = TopicShiftDetector(llm_adapter=RealisticCloudLLM())
        history = [
            HumanMessage(content="Tell me about Python asyncio."),
            AIMessage(content="asyncio is a library to write concurrent code."),
        ]
        # Call WITHOUT passing timeout_seconds to ensure default 2.0s is utilized
        result = await detector.detect_topic_shift(history, "How do black holes form?")
        assert result.is_topic_shift is True
        assert result.new_topic == "Stellar Evolution"


# ============================================================================
# 2. SmartSessionManager Time Decay & Lifecycle Tests
# ============================================================================


class TestSmartSessionManager:
    """Unit tests for 3-stage time decay routing and working memory injection."""

    @pytest.mark.asyncio
    async def test_time_decay_stage_1_short_term_maintains_session(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Stage 1 (<= 15 minutes): Session is maintained with full working memory."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        now = datetime.now(UTC)
        # Create an initial session active 5 minutes ago (300 seconds)
        session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Quantum Discussion"
        )
        await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="What is entanglement?",
            assistant_content="Entanglement is a quantum phenomenon where particles share states.",
        )
        session.last_active_at = now - timedelta(minutes=5)
        await async_db_session.commit()

        # Route incoming query 5 minutes later
        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session.id,
            incoming_message="Can it be used for faster-than-light communication?",
            now=now,
        )

        assert decision.action == SessionRoutingAction.MAINTAIN
        assert routed_session.id == session.id
        assert not decision.is_reset
        assert len(working_memory) == 2
        assert isinstance(working_memory[0], HumanMessage)
        assert isinstance(working_memory[1], AIMessage)

    @pytest.mark.asyncio
    async def test_time_decay_stage_2_mid_term_branches_with_bridge_summary(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Stage 2 (15m < delta <= 2h): Previous session archived, new session created with bridge summary."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(
            canned_response="User discussed warp drive theories and requested fuel calculations."
        )
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        now = datetime.now(UTC)
        # Session active 45 minutes ago
        old_session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Warp Drive Discussion"
        )
        await manager.record_turn(
            session_id=old_session.id,
            user_id=seed_test_user.id,
            user_content="Calculate antimatter requirements for Alpha Centauri trip.",
            assistant_content="Antimatter required is approximately 100 grams.",
        )
        old_session.last_active_at = now - timedelta(minutes=45)
        await async_db_session.commit()

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=old_session.id,
            incoming_message="Continue with shielding requirements.",
            now=now,
        )

        assert decision.action == SessionRoutingAction.BRANCH_BRIDGE
        assert routed_session.id != old_session.id
        assert routed_session.parent_session_id == old_session.id
        assert (
            routed_session.bridge_summary
            == "User discussed warp drive theories and requested fuel calculations."
        )
        assert old_session.status == "archived"

        # Working memory should contain bridge summary system context
        assert len(working_memory) == 1
        assert isinstance(working_memory[0], SystemMessage)
        assert "warp drive theories" in str(working_memory[0].content)

    @pytest.mark.asyncio
    async def test_time_decay_stage_3_long_term_resets_fresh_session(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Stage 3 (> 2 hours): Previous session archived, completely fresh session initialized."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        now = datetime.now(UTC)
        # Session active 5 hours ago (300 minutes)
        old_session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Ancient Session"
        )
        await manager.record_turn(
            session_id=old_session.id,
            user_id=seed_test_user.id,
            user_content="Old question.",
            assistant_content="Old answer.",
        )
        old_session.last_active_at = now - timedelta(hours=5)
        await async_db_session.commit()

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=old_session.id,
            incoming_message="TARS, start our daily diagnostics.",
            now=now,
        )

        assert decision.action == SessionRoutingAction.FRESH_RESET
        assert routed_session.id != old_session.id
        assert routed_session.parent_session_id is None
        assert routed_session.status == "active"
        assert old_session.status == "archived"
        assert len(working_memory) == 0

    @pytest.mark.asyncio
    async def test_natural_reset_command_archives_and_resets(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Explicit reset command archives current active session and starts a new one immediately."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        # Active session created recently
        session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Pre-Reset Session"
        )
        await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="Some message",
            assistant_content="Some response",
        )

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=session.id,
            incoming_message="TARS, 리셋해줘",
        )

        assert decision.action == SessionRoutingAction.NATURAL_RESET
        assert decision.is_reset is True
        assert routed_session.id != session.id
        assert routed_session.status == "active"
        assert session.status == "archived"
        assert len(working_memory) == 0

    @pytest.mark.asyncio
    async def test_topic_shift_routing_branches_new_session(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Semantic topic shift branches a new task session with parent linkage."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter(
            canned_response='{"is_topic_shift": true, "new_topic": "Gardening Tips"}'
        )
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        now = datetime.now(UTC)
        old_session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Quantum Computing"
        )
        await manager.record_turn(
            session_id=old_session.id,
            user_id=seed_test_user.id,
            user_content="How do qubits maintain superposition?",
            assistant_content="Through isolation from environmental decoherence.",
        )

        routed_session, working_memory, decision = await manager.route_session(
            user_id=seed_test_user.id,
            requested_session_id=old_session.id,
            incoming_message="How often should I water my tomato plants?",
            now=now,
        )

        assert decision.action == SessionRoutingAction.TOPIC_SHIFT
        assert routed_session.id != old_session.id
        assert routed_session.parent_session_id == old_session.id
        assert routed_session.title == "Gardening Tips"
        assert old_session.status == "archived"
        assert len(working_memory) == 0

    @pytest.mark.asyncio
    async def test_record_turn_persists_messages_and_updates_activity(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """record_turn creates ChatMessage rows and refreshes session last_active_at."""
        storage = FileStorageManager(base_dir=temp_storage_root)
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
        )

        session = await manager.create_new_session(user_id=seed_test_user.id, title="New Dialogue")
        original_last_active = session.last_active_at

        await asyncio.sleep(0.01)
        user_msg, assistant_msg = await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="TARS, calculate landing vector.",
            assistant_content="Landing vector computed. 12 degrees retro.",
            user_tokens=5,
            assistant_tokens=8,
        )

        assert user_msg.role == "user"
        assert user_msg.tokens == 5
        assert assistant_msg.role == "assistant"
        assert assistant_msg.tokens == 8

        # Session refreshed
        reloaded = await manager.get_session_by_id(session.id)
        assert reloaded is not None
        assert reloaded.last_active_at > original_last_active
        assert len(reloaded.messages) == 2
        assert reloaded.title == "TARS, calculate landing vector."

    @pytest.mark.asyncio
    async def test_archive_session_dispatches_task_when_background_tasks_is_none(
        self,
        async_db_session: AsyncSession,
        seed_test_user: User,
        temp_storage_root: Any,
    ) -> None:
        """Verify archive_session falls back to asyncio.create_task registered with _background_node_tasks when background_tasks is None."""
        from tars.extractor.worker import SelfEvolvingKnowledgeWorker
        from tars.orchestrator.nodes import _background_node_tasks

        _background_node_tasks.clear()

        storage = FileStorageManager(base_dir=temp_storage_root)
        mock_llm = MockLLMAdapter()
        manager = SmartSessionManager(
            db_session=async_db_session,
            storage_manager=storage,
            llm_adapter=mock_llm,
        )

        session = await manager.create_new_session(
            user_id=seed_test_user.id, title="Archival Fallback Test"
        )
        await manager.record_turn(
            session_id=session.id,
            user_id=seed_test_user.id,
            user_content="Turn 1 Question",
            assistant_content="Turn 1 Answer",
        )

        task_started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def controlled_extract(*args: Any, **kwargs: Any) -> list[Any]:
            task_started.set()
            await allow_finish.wait()
            return []

        with patch.object(
            SelfEvolvingKnowledgeWorker, "extract_and_sync", side_effect=controlled_extract
        ):
            # Archive with background_tasks=None
            await manager.archive_session(session, background_tasks=None)

            # Wait for task to start
            await asyncio.wait_for(task_started.wait(), timeout=1.0)

            # Verify task was registered in _background_node_tasks
            pending = [t for t in _background_node_tasks if not t.done()]
            assert len(pending) >= 1, (
                "Expected background task to be registered in _background_node_tasks"
            )
            bg_task = pending[0]

            allow_finish.set()
            await bg_task
            assert bg_task.done()
            assert not bg_task.cancelled()
            assert bg_task not in _background_node_tasks

    @pytest.mark.asyncio
    async def test_run_async_knowledge_extraction_cooperative_cancellation(
        self,
        temp_storage_root: Any,
    ) -> None:
        """Verify _run_async_knowledge_extraction re-raises asyncio.CancelledError when cancelled."""
        from tars.core.session.manager import _run_async_knowledge_extraction
        from tars.extractor.worker import SelfEvolvingKnowledgeWorker

        storage = FileStorageManager(base_dir=temp_storage_root)

        async def slow_extract(*args: Any, **kwargs: Any) -> list[Any]:
            await asyncio.sleep(10.0)
            return []

        with patch.object(
            SelfEvolvingKnowledgeWorker, "extract_and_sync", side_effect=slow_extract
        ):
            messages = [HumanMessage(content="Q"), AIMessage(content="A")]
            task = asyncio.create_task(
                _run_async_knowledge_extraction(
                    user_id="user_cancel_test",
                    messages=messages,
                    storage_manager=storage,
                    extractor_llm=MockLLMAdapter(),
                )
            )
            await asyncio.sleep(0.01)
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

            assert task.cancelled()
