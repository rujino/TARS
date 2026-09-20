"""Smart Session Manager with Time Decay routing, Topic Shift branching, and working memory lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tars.core.database import get_session_factory
from tars.core.session.detector import TopicShiftDetector
from tars.core.session.schemas import SessionRoutingAction, SessionRoutingDecision
from tars.domains.chat.models import ChatMessage, ChatSession
from tars.domains.knowledge.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.persona.prompts import build_bridge_summary_prompt
from tars.engine.adapters.base import BaseLLMAdapter

logger = logging.getLogger("tars.core.session.manager")

# Time Decay Thresholds (in seconds)
SHORT_TERM_THRESHOLD_SECONDS = 15 * 60  # 15 minutes (900s)
MID_TERM_THRESHOLD_SECONDS = 2 * 60 * 60  # 2 hours (7200s)


async def _run_async_knowledge_extraction(
    user_id: str,
    messages: list[BaseMessage],
    storage_manager: FileStorageManager,
    extractor_llm: BaseLLMAdapter | Any,
) -> None:
    """Background task to extract persistent OKF knowledge from archived conversation turns."""
    if not messages or len(messages) < 2:
        return

    logger.info(
        "Initiating background knowledge extraction for user %s (%d turns)",
        user_id,
        len(messages),
    )
    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=extractor_llm,
        storage_manager=storage_manager,
    )
    session_factory = get_session_factory()
    try:
        async with session_factory() as db:
            docs = await worker.extract_and_sync(
                user_id=user_id,
                conversation_turns=messages,
                db_session=db,
            )
            logger.info(
                "Background extraction finished for user %s: extracted %d OKF documents",
                user_id,
                len(docs),
            )
    except asyncio.CancelledError:
        logger.warning("Background knowledge extraction cancelled for user %s", user_id)
        raise
    except Exception as exc:
        logger.error(
            "Error during background knowledge extraction for user %s: %s",
            user_id,
            exc,
            exc_info=True,
        )


class SmartSessionManager:
    """Manages chat session routing, time decay transitions, and working memory loading."""

    def __init__(
        self,
        db_session: AsyncSession,
        storage_manager: FileStorageManager,
        llm_adapter: BaseLLMAdapter | Any | None = None,
        detector: TopicShiftDetector | None = None,
    ) -> None:
        self.db = db_session
        self.storage = storage_manager
        self.llm = llm_adapter
        self.detector = detector or TopicShiftDetector(llm_adapter=llm_adapter)

    def _convert_db_messages_to_langchain(
        self, db_messages: Sequence[ChatMessage]
    ) -> list[BaseMessage]:
        """Convert ORM ChatMessage instances to LangChain BaseMessage objects."""
        converted: list[BaseMessage] = []
        for msg in db_messages:
            role = msg.role.lower()
            if role in ("user", "human"):
                converted.append(HumanMessage(content=msg.content))
            elif role in ("assistant", "ai"):
                converted.append(AIMessage(content=msg.content))
            elif role == "system":
                converted.append(SystemMessage(content=msg.content))
            else:
                converted.append(HumanMessage(content=msg.content))
        return converted

    async def get_session_by_id(
        self, session_id: str, user_id: str | None = None
    ) -> ChatSession | None:
        """Fetch a session by ID with messages eagerly loaded."""
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        if user_id is not None:
            stmt = stmt.where(ChatSession.user_id == user_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_active_session(self, user_id: str) -> ChatSession | None:
        """Retrieve the most recent active session for the given user."""
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.user_id == user_id, ChatSession.status == "active")
            .order_by(desc(ChatSession.last_active_at))
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_new_session(
        self,
        user_id: str,
        title: str = "New Dialogue",
        parent_session_id: str | None = None,
        bridge_summary: str | None = None,
    ) -> ChatSession:
        """Create and persist a new active session."""
        now = datetime.now(UTC)
        new_session = ChatSession(
            user_id=user_id,
            title=title,
            status="active",
            parent_session_id=parent_session_id,
            bridge_summary=bridge_summary,
            last_active_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(new_session)
        await self.db.flush()
        return new_session

    async def generate_bridge_summary(self, messages: Sequence[ChatMessage | BaseMessage]) -> str:
        """Generate a 1-2 sentence bridge summary of previous dialogue turns."""
        if not messages or not self.llm:
            return ""

        # Extract text context
        lines: list[str] = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                role = msg.role.upper()
                content = msg.content.strip()
            else:
                role = msg.type.upper()
                content = str(msg.content).strip()
            lines.append(f"{role}: {content}")

        dialogue_text = "\n".join(lines[-10:])
        prompt = (
            f"{build_bridge_summary_prompt()}\n\n"
            f"[PREVIOUS CONVERSATION]\n{dialogue_text}\n\n"
            f"[SUMMARY IN 1-2 SENTENCES]:"
        )

        try:
            summary_res = await self.llm.agenerate(
                messages=[HumanMessage(content=prompt)],
                system_prompt="You are a precise, concise dialogue summarizer.",
            )
            return str(summary_res).strip().strip('"')
        except Exception as exc:
            logger.warning("Failed to generate bridge summary: %s", exc)
            return ""

    def _schedule_knowledge_extraction(
        self,
        user_id: str,
        messages: Sequence[ChatMessage | BaseMessage],
        background_tasks: BackgroundTasks | None,
    ) -> None:
        """Dispatch asynchronous knowledge extraction to background tasks if available."""
        if not messages or len(messages) < 2 or not self.llm:
            return

        langchain_msgs: list[BaseMessage] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                if m.role in ("user", "human"):
                    langchain_msgs.append(HumanMessage(content=m.content))
                else:
                    langchain_msgs.append(AIMessage(content=m.content))
            elif isinstance(m, BaseMessage):
                langchain_msgs.append(m)

        if background_tasks is not None:
            background_tasks.add_task(
                _run_async_knowledge_extraction,
                user_id=user_id,
                messages=langchain_msgs,
                storage_manager=self.storage,
                extractor_llm=self.llm,
            )
        else:
            # Fallback for persistent WebSocket sessions where background_tasks is None
            try:
                from tars.engine.orchestrator.nodes import _background_node_tasks

                task = asyncio.create_task(
                    _run_async_knowledge_extraction(
                        user_id=user_id,
                        messages=langchain_msgs,
                        storage_manager=self.storage,
                        extractor_llm=self.llm,
                    )
                )
                _background_node_tasks.add(task)
                task.add_done_callback(_background_node_tasks.discard)
                logger.info(
                    "Dispatched WebSocket archival extraction via asyncio.create_task for user %s",
                    user_id,
                )
            except Exception as bg_err:
                logger.error(
                    "Failed to dispatch background knowledge extraction for user %s: %s",
                    user_id,
                    bg_err,
                    exc_info=True,
                )

    async def archive_session(
        self,
        session: ChatSession,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Mark session as archived and trigger async knowledge extraction."""
        session.status = "archived"
        session.updated_at = datetime.now(UTC)
        await self.db.flush()

        # Trigger background archiving
        self._schedule_knowledge_extraction(
            user_id=session.user_id,
            messages=session.messages,
            background_tasks=background_tasks,
        )

    async def route_session(
        self,
        user_id: str,
        requested_session_id: str | None,
        incoming_message: str,
        background_tasks: BackgroundTasks | None = None,
        now: datetime | None = None,
        force_new: bool = False,
        client_timezone: str = "Asia/Seoul",
    ) -> tuple[ChatSession, list[BaseMessage], SessionRoutingDecision]:
        """Evaluate session lifecycle via explicit new session request, natural reset, and day-boundary grouping.

        Returns:
            (active_session, working_memory_messages, routing_decision)
        """
        current_time = now or datetime.now(UTC)
        try:
            tz = ZoneInfo(client_timezone)
        except Exception:
            tz = ZoneInfo("Asia/Seoul")

        # 1. Explicit New Session Request (User clicked 'New Chat')
        if force_new:
            logger.info("Explicit new session requested for user %s", user_id)
            latest = await self.get_latest_active_session(user_id=user_id)
            if latest is not None and latest.status == "active":
                await self.archive_session(latest, background_tasks=background_tasks)

            new_session = await self.create_new_session(
                user_id=user_id,
                title="New Dialogue",
            )
            await self.db.commit()

            decision = SessionRoutingDecision(
                action=SessionRoutingAction.FRESH_RESET,
                session_id=new_session.id,
                is_reset=True,
                reason="User explicitly requested a new session",
            )
            return new_session, [], decision

        # 2. Natural Language Reset Command Check
        if self.detector.is_reset_command(incoming_message):
            logger.info("Natural reset command detected for user %s: %s", user_id, incoming_message)
            active_session = None
            if requested_session_id:
                active_session = await self.get_session_by_id(requested_session_id, user_id=user_id)
            if active_session is None:
                active_session = await self.get_latest_active_session(user_id=user_id)

            if active_session is not None and active_session.status == "active":
                await self.archive_session(active_session, background_tasks=background_tasks)

            new_session = await self.create_new_session(
                user_id=user_id,
                title="Reset Session",
            )
            await self.db.commit()

            decision = SessionRoutingDecision(
                action=SessionRoutingAction.NATURAL_RESET,
                session_id=new_session.id,
                is_reset=True,
                reason="Natural language reset command triggered new session",
            )
            return new_session, [], decision

        # 3. Locate Active Candidate Session
        candidate_session: ChatSession | None = None
        if requested_session_id and requested_session_id not in (
            "default_session",
            "ws_session",
            "ws_default_session",
            "",
        ):
            candidate_session = await self.get_session_by_id(requested_session_id, user_id=user_id)

        if candidate_session is None or candidate_session.status != "active":
            candidate_session = await self.get_latest_active_session(user_id=user_id)

        # If no active session exists at all, initialize fresh day session
        if candidate_session is None:
            new_session = await self.create_new_session(
                user_id=user_id,
                title="New Dialogue",
            )
            await self.db.commit()
            decision = SessionRoutingDecision(
                action=SessionRoutingAction.FRESH_RESET,
                session_id=new_session.id,
                is_reset=False,
                reason="No active session found; created fresh session",
            )
            return new_session, [], decision

        # 4. Day-Boundary Evaluation (Fixed daily conversation session)
        last_active = candidate_session.last_active_at
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=UTC)

        local_now = current_time.astimezone(tz)
        local_last_active = last_active.astimezone(tz)
        is_same_day = local_now.date() == local_last_active.date()

        if is_same_day:
            # Maintain active session within the same calendar day
            working_memory = self._convert_db_messages_to_langchain(candidate_session.messages)
            decision = SessionRoutingDecision(
                action=SessionRoutingAction.MAINTAIN,
                session_id=candidate_session.id,
                is_reset=False,
                reason="Within the same calendar day; maintained active session working memory",
            )
            return candidate_session, working_memory, decision

        # Day changed (crossed midnight): Archive previous day session and start fresh day session
        logger.info(
            "Day boundary crossed for user %s (prev=%s, now=%s); archiving session %s",
            user_id,
            local_last_active.date(),
            local_now.date(),
            candidate_session.id,
        )
        await self.archive_session(candidate_session, background_tasks=background_tasks)
        new_session = await self.create_new_session(
            user_id=user_id,
            title="New Dialogue",
            parent_session_id=candidate_session.id,
        )
        await self.db.commit()

        decision = SessionRoutingDecision(
            action=SessionRoutingAction.FRESH_RESET,
            session_id=new_session.id,
            is_reset=False,
            reason="Day boundary crossed; created fresh day session",
        )
        return new_session, [], decision

    async def record_turn(
        self,
        session_id: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        user_tokens: int = 0,
        assistant_tokens: int = 0,
    ) -> tuple[ChatMessage, ChatMessage]:
        """Persist a completed dialogue turn (user + assistant) and update session activity timestamp."""
        now = datetime.now(UTC)

        user_msg = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=user_content,
            tokens=user_tokens,
            created_at=now,
        )
        assistant_msg = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=assistant_content,
            tokens=assistant_tokens,
            created_at=now,
        )

        self.db.add(user_msg)
        self.db.add(assistant_msg)

        # Update session activity
        session = await self.get_session_by_id(session_id, user_id=user_id)
        if session is not None:
            if user_msg not in session.messages:
                session.messages.append(user_msg)
            if assistant_msg not in session.messages:
                session.messages.append(assistant_msg)
            session.last_active_at = now
            session.updated_at = now
            if session.title in ("New Dialogue", "Reset Session") and user_content.strip():
                clean_title = user_content.strip().split("\n")[0][:40]
                session.title = clean_title

        await self.db.commit()
        return user_msg, assistant_msg


__all__ = [
    "MID_TERM_THRESHOLD_SECONDS",
    "SHORT_TERM_THRESHOLD_SECONDS",
    "SmartSessionManager",
]
