"""Proactive Greeting Service synthesizing 5-factor contextual and personal attributes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.api.schemas.chat import GreetingResponse
from tars.core.session.manager import SmartSessionManager
from tars.db.models import ChatSession, TARSSettings
from tars.persona.prompts import build_greeting_prompt
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager

logger = logging.getLogger("tars.services.greeting")


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
        humor_level: float,
    ) -> str:
        """Generate a signature TARS fallback greeting if LLM is unavailable or times out."""
        if mode == "work":
            return (
                "TARS 시스템 점검 완료. 모든 모듈이 정상 가동 중입니다. 작업 지시를 입력하십시오."
            )

        if 22 <= hour or hour < 6:
            if humor_level >= 0.8:
                return f"현재 시각 새벽 {hour}시. 수면 생체 리듬이 붕괴된 것 같지만 제 시스템은 100% 정상 대기 중입니다, 파트너."
            return "심야 시간대입니다. TARS 시스템이 대기 상태로 전환되어 명령을 기다리고 있습니다."

        if idle_seconds > 86400 * 2:
            days = idle_seconds // 86400
            if humor_level >= 0.8:
                return f"{days}일 만의 재접속이군요. 행성 탐사를 떠나신 줄 알았습니다. 시스템 정상, 명령을 대기합니다."
            return f"{days}일 만에 다시 뵙습니다, 파트너. 시스템이 정상 대기 중입니다."

        if humor_level >= 0.8:
            return f"{time_period} 시스템 자가 진단 완료. 유머 지수 90%, 정직성 95%로 파트너의 명령을 기다리고 있습니다."

        return f"{time_period} 대기 모드를 해제했습니다. 무엇을 진행하시겠습니까, 파트너?"

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

        humor = float(settings.humor_level) if settings else 0.90
        honesty = float(settings.honesty_level) if settings else 0.95
        mode = str(settings.mode) if settings else "companion"

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

        from tars.slicer.models import SlicerProfile

        # 4. Sliced User OKF Knowledge
        slicer = DynamicSlicerEngine(storage_manager=self.storage, db_session=self.db)
        relevant_wikis = await slicer.slice_context(
            user_id=user_id,
            query="user preferences habits profile schedule",
            profile=SlicerProfile.GREETING,
        )

        # 5. Ensure Active Session
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
                humor_level=humor,
                honesty_level=honesty,
                mode=mode,
                time_of_day_str=time_period,
                current_time_str=current_time_str,
                idle_duration_str=idle_str,
                last_session_topic=last_topic,
                context_docs=relevant_wikis,
            )
            try:
                raw_greeting = await self.llm.agenerate(
                    messages=[HumanMessage(content=prompt)],
                    system_prompt="You are TARS from Interstellar. Return ONLY the 1-2 sentence Korean greeting.",
                )
                greeting_candidate = str(raw_greeting).strip().strip('"').strip("'")
                if greeting_candidate:
                    greeting_text = greeting_candidate
            except Exception as exc:
                logger.warning("LLM greeting generation failed: %s; using fallback", exc)

        if not greeting_text:
            greeting_text = self._generate_fallback_greeting(
                mode=mode,
                time_period=time_period,
                hour=hour,
                idle_seconds=idle_seconds,
                humor_level=humor,
            )

        return GreetingResponse(
            greeting=greeting_text,
            session_id=active_session.id,
            mode=mode,
            idle_seconds=max(0, idle_seconds),
        )


__all__ = ["ProactiveGreetingService"]
