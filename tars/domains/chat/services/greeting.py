"""Proactive Greeting Service synthesizing 5-factor contextual and personal attributes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.domains.chat.models import ChatSession
from tars.domains.chat.schemas import GreetingResponse
from tars.domains.knowledge.slicer.engine import DynamicSlicerEngine
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.persona.models import TARSSettings
from tars.domains.persona.prompts import build_greeting_prompt
from tars.engine.adapters.base import BaseLLMAdapter

logger = logging.getLogger("tars.domains.chat.services.greeting")


class ProactiveGreetingService:
    """Generates situational, personalized, and witty proactive greetings upon client startup."""

    def __init__(
        self,
        db_session: AsyncSession,
        storage_manager: FileStorageManager,
        llm_adapter: BaseLLMAdapter | Any | None = None,
    ) -> None:
        self.db = db_session
        self.storage = storage_manager
        self.llm = llm_adapter

    def _get_time_of_day(self, hour: int) -> tuple[str, str]:
        """Categorize hour into Korean time period and formatted description."""
        if 6 <= hour < 11:
            return "아침", f"오전 {hour}시"
        if 11 <= hour < 14:
            return "점심", f"낮 {hour}시"
        if 14 <= hour < 18:
            return "오후", f"오후 {hour - 12 if hour > 12 else hour}시"
        if 18 <= hour < 22:
            return "저녁", f"저녁 {hour - 12}시"
        # 22시 ~ 06시
        display_hour = hour if hour < 12 else hour - 12
        return "심야/새벽", f"새벽 {display_hour}시"

    def _format_idle_duration(self, idle_seconds: int) -> str:
        """Format seconds into human-readable Korean idle time description."""
        if idle_seconds < 0:
            return "첫 접속 (신규 사용자)"
        if idle_seconds < 60:
            return "방금 전 (1분 이내)"
        if idle_seconds < 3600:
            return f"{idle_seconds // 60}분 만의 재접속"
        if idle_seconds < 86400:
            return f"{idle_seconds // 3600}시간 만의 재접속"
        days = idle_seconds // 86400
        return f"{days}일 만의 재접속"

    def _generate_fallback_greeting(
        self,
        mode: str,
        time_period: str,
        hour: int,
        idle_seconds: int,
    ) -> str:
        """Generate a thoughtful TARS personal attendant fallback greeting if LLM is unavailable or times out."""
        norm_mode = "attend" if mode in ("attend", "companion") else "task"
        if norm_mode == "task":
            return (
                "주인님, TARS 작업 모드 가동되었습니다. 집중할 과업이나 지시사항을 말씀해 주십시오."
            )

        if 22 <= hour or hour < 6:
            return f"주인님, 늦은 밤({hour}시)입니다. 오늘 하루도 고생 많으셨습니다. 무리하지 마시고 편안히 쉬시길 바랍니다."

        if idle_seconds > 86400 * 2:
            days = idle_seconds // 86400
            return f"주인님, {days}일 만에 다시 뵙습니다. 그동안 평안하셨는지요? 언제나 곁에서 이야기를 기다리고 있었습니다."

        return f"주인님, {time_period}의 시간을 보필하게 되어 기쁩니다. 오늘 어떤 생각이나 이야기를 나누고 싶으신가요?"

    async def generate_greeting(
        self,
        user_id: str,
        client_timezone: str = "Asia/Seoul",
        client_time: datetime | None = None,
    ) -> GreetingResponse:
        """Construct a 5-factor proactive greeting combining time, idle gap, context, OKF slices, and persona."""
        # 1. Resolve Local Time
        tz: tzinfo
        try:
            tz = ZoneInfo(client_timezone)
        except Exception:
            tz = timezone(timedelta(hours=9))  # Default KST

        now_utc = datetime.now(UTC)
        local_time = client_time.astimezone(tz) if client_time else now_utc.astimezone(tz)
        hour = local_time.hour
        time_period, time_str = self._get_time_of_day(hour)
        current_time_str = local_time.strftime("%Y-%m-%d %H:%M")

        # 2. Retrieve Persona Settings
        stmt_settings = select(TARSSettings).where(TARSSettings.user_id == user_id)
        res_settings = await self.db.execute(stmt_settings)
        settings = res_settings.scalar_one_or_none()

        mode = str(settings.mode) if settings else "attend"

        # 3. Locate Latest Session & Idle Calculation
        stmt_session = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(desc(ChatSession.last_active_at))
            .limit(1)
        )
        res_session = await self.db.execute(stmt_session)
        last_session = res_session.scalar_one_or_none()

        last_topic = None
        if last_session is not None:
            last_active = last_session.last_active_at
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=UTC)
            idle_seconds = max(0, int((now_utc - last_active).total_seconds()))
            if last_session.title and last_session.title != "New Dialogue":
                last_topic = last_session.title
            elif last_session.bridge_summary:
                last_topic = last_session.bridge_summary
        else:
            idle_seconds = -1  # Brand new user

        idle_str = self._format_idle_duration(idle_seconds)

        from tars.domains.knowledge.slicer.schemas import SlicerProfile

        # 4. Sliced User OKF Knowledge
        slicer = DynamicSlicerEngine(storage_manager=self.storage, db_session=self.db)
        relevant_wikis = await slicer.slice_context(
            user_id=user_id,
            query="user preferences habits profile schedule",
            profile=SlicerProfile.GREETING,
        )

        # 5. Ensure Active Session
        from tars.core.session.manager import SmartSessionManager

        session_mgr = SmartSessionManager(
            db_session=self.db,
            storage_manager=self.storage,
            llm_adapter=self.llm,
        )
        active_session = await session_mgr.get_latest_active_session(user_id=user_id)
        if active_session is None:
            active_session = await session_mgr.create_new_session(
                user_id=user_id,
                title="New Dialogue",
            )
            await self.db.commit()

        # 6. Generate Greeting via LLM or Fallback
        greeting_text = ""
        if self.llm is not None:
            prompt = build_greeting_prompt(
                mode=mode,
                time_of_day_str=time_period,
                current_time_str=current_time_str,
                idle_duration_str=idle_str,
                last_session_topic=last_topic,
                context_docs=relevant_wikis,
            )
            try:
                raw_greeting = await asyncio.wait_for(
                    self.llm.agenerate(
                        messages=[HumanMessage(content=prompt)],
                        system_prompt="You are TARS (Thoughtful Adaptive Reflective System), personal attendant to 주인님. Return ONLY the 1-2 sentence Korean greeting.",
                    ),
                    timeout=3.0,
                )
                greeting_candidate = str(raw_greeting).strip().strip('"').strip("'")
                if greeting_candidate:
                    greeting_text = greeting_candidate
            except (asyncio.TimeoutError, TimeoutError):
                logger.warning(
                    "Greeting LLM generation timed out (>3.0s); falling back to deterministic template."
                )
            except Exception as exc:
                logger.warning("LLM greeting generation failed: %s; using fallback", exc)

        if not greeting_text:
            greeting_text = self._generate_fallback_greeting(
                mode=mode,
                time_period=time_period,
                hour=hour,
                idle_seconds=idle_seconds,
            )

        return GreetingResponse(
            greeting=greeting_text,
            session_id=active_session.id,
            mode=mode,
            idle_seconds=max(0, idle_seconds),
        )


__all__ = ["ProactiveGreetingService"]
