"""Topic shift and natural language reset command detector."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from tars.adapters.base import BaseLLMAdapter
from tars.core.session.models import TopicShiftResult
from tars.db.models import ChatMessage

logger = logging.getLogger("tars.core.session.detector")

# Regex pattern matching natural language reset commands in Korean and English
RESET_COMMAND_REGEX = re.compile(
    r"^\s*(?:tars|타스)?\s*[,:]?\s*"
    r"(?:"
    r"리셋(?:해(?:줘)?|하자|합시다|시켜줘|부탁해)?"
    r"|초기화(?:해(?:줘)?|하자|합시다|시켜줘|부탁해)?"
    r"|새(?:로운)?\s*(?:주제|대화|세션)(?:\s*(?:로\s*)?시작(?:해(?:줘)?|하자|합시다|해)?)?"
    r"|대화\s*초기화(?:해(?:줘)?|하자|합시다|시켜줘|부탁해)?"
    r"|기억\s*(?:지워(?:줘)?|삭제(?:해(?:줘)?)?|포맷(?:해(?:줘)?)?)"
    r"|세션\s*(?:리셋|초기화)(?:해(?:줘)?|하자|합시다|시켜줘|부탁해)?"
    r"|reset(?:\s*(?:session|chat|now))?"
    r"|clear\s*(?:chat|history|session)"
    r"|start\s*(?:new\s*(?:topic|session|chat|conversation))"
    r"|new\s*(?:chat|session)"
    r")\s*[.!?~]*\s*$",
    re.IGNORECASE,
)

TOPIC_SHIFT_PROMPT = """You are the TARS Topic Shift Detector.
Analyze the following recent dialogue turns and the user's incoming query.
Determine whether the incoming query introduces a completely different subject, domain, or task that represents a clear contextual break from the ongoing dialogue.

[RECENT CONTEXT]
{context}

[INCOMING QUERY]
{query}

Respond with ONLY a valid JSON object adhering strictly to this schema:
{{"is_topic_shift": true | false, "new_topic": "<brief 2-4 word topic title or null>"}}
"""


class TopicShiftDetector:
    """Detects explicit session reset commands and semantic topic shifts."""

    def __init__(self, llm_adapter: BaseLLMAdapter | Any | None = None) -> None:
        self.llm_adapter = llm_adapter

    def is_reset_command(self, query: str) -> bool:
        """Check if the given query is a natural language session reset command."""
        if not query or not query.strip():
            return False
        cleaned = query.strip()
        return bool(RESET_COMMAND_REGEX.match(cleaned))

    def _extract_text_context(self, turns: Sequence[ChatMessage | BaseMessage]) -> str:
        """Convert sequence of chat messages into a concise string for LLM analysis."""
        lines: list[str] = []
        for turn in turns[-6:]:  # Max last 3 full turns (6 messages)
            if isinstance(turn, ChatMessage):
                role = turn.role.upper()
                content = turn.content.strip()
            else:
                role = turn.type.upper()
                content = str(turn.content).strip()
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _clean_json_str(self, raw_text: str) -> str:
        """Strip markdown fences and whitespace from raw text."""
        text = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    async def detect_topic_shift(
        self,
        recent_turns: Sequence[ChatMessage | BaseMessage],
        new_query: str,
        timeout_seconds: float = 0.5,
    ) -> TopicShiftResult:
        """Evaluate whether new_query represents a semantic topic shift from recent dialogue context.

        Uses a fast timeout (default 500ms) with safe fallback to False to guarantee low latency.
        """
        if not recent_turns or len(recent_turns) < 2 or not new_query.strip():
            return TopicShiftResult(is_topic_shift=False)

        if self.llm_adapter is None:
            return TopicShiftResult(is_topic_shift=False)

        context_str = self._extract_text_context(recent_turns)
        formatted_prompt = TOPIC_SHIFT_PROMPT.format(
            context=context_str,
            query=new_query.strip(),
        )

        try:
            # Enforce strict circuit-breaker timeout
            response_coro = self.llm_adapter.agenerate(
                messages=[HumanMessage(content=formatted_prompt)],
                system_prompt="You are a fast, lightweight topic shift classifier. Output JSON only.",
            )
            raw_response = await asyncio.wait_for(response_coro, timeout=timeout_seconds)
            cleaned_json = self._clean_json_str(str(raw_response))
            data = json.loads(cleaned_json)
            is_shift = bool(data.get("is_topic_shift", False))
            new_topic = data.get("new_topic")
            if is_shift and not new_topic:
                new_topic = new_query.strip()[:30]
            return TopicShiftResult(
                is_topic_shift=is_shift,
                new_topic=new_topic,
            )
        except TimeoutError:
            logger.debug(
                "Topic shift detection timed out after %.2fs; defaulting to False",
                timeout_seconds,
            )
            return TopicShiftResult(is_topic_shift=False)
        except Exception as exc:
            logger.debug("Topic shift detection failed (%s); defaulting to False", exc)
            return TopicShiftResult(is_topic_shift=False)


__all__ = [
    "RESET_COMMAND_REGEX",
    "TopicShiftDetector",
]
