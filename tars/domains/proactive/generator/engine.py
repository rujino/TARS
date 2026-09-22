"""Orchestrator engine for proactive message synthesis."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tars.domains.persona.registry import PersonaRegistry, get_default_registry
from tars.domains.proactive.generator.prompts import build_proactive_prompt
from tars.domains.proactive.generator.schemas import GeneratorInput, GeneratorOutput
from tars.engine.adapters.base import BaseLLMAdapter
from tars.engine.adapters.gemini import GeminiAdapter

logger = logging.getLogger("tars.domains.proactive.generator.engine")


class ProactiveMessageGenerator:
    """Synthesizes context-grounded proactive utterance messages using LLM and persona voices."""

    def __init__(
        self,
        llm_adapter: BaseLLMAdapter | None = None,
        persona_registry: PersonaRegistry | None = None,
    ) -> None:
        self.llm_adapter = llm_adapter or GeminiAdapter(model_name="gemini-2.0-flash")
        self.persona_registry = persona_registry or get_default_registry()

    async def generate(self, inp: GeneratorInput) -> GeneratorOutput:
        """Synthesize a single proactive utterance based on the given context.

        Guaranteed:
            - Conforms strictly to Zero-Example prompting.
            - Retries on empty or excessively truncated outputs.
        """
        # 1. Resolve persona definition
        persona_def = None
        try:
            persona_def = self.persona_registry.get(inp.persona_id)
        except Exception:
            logger.debug("Persona '%s' not registered; falling back to default voice", inp.persona_id)

        # 2. Build 5-layer prompt
        system_prompt = build_proactive_prompt(inp, persona_def)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content="주인님과의 대화를 자연스럽게 시작하는 선제적 첫 발화를 완성하십시오."
            ),
        ]

        # 3. Generate with retry guard
        content = ""
        for attempt in range(2):
            try:
                response = await self.llm_adapter.agenerate(messages)
                candidate_text = response.content.strip()

                # Basic validation: ensure non-empty and reasonable length
                if len(candidate_text) >= 10:
                    content = candidate_text
                    break
                logger.warning(
                    "Proactive generation attempt %d produced short output: '%s'",
                    attempt + 1,
                    candidate_text,
                )
            except Exception as exc:
                logger.error("Error during proactive LLM call (attempt %d): %s", attempt + 1, exc)

        if not content:
            # Fallback default utterance
            content = "주인님, 오늘 남겨두신 기록과 과업 관련하여 살피실 부분이 있는지 여쭙고자 합니다."

        return GeneratorOutput(
            content=content,
            persona_id=inp.persona_id,
            schedule_type=inp.schedule_type,
        )


__all__ = ["ProactiveMessageGenerator"]
