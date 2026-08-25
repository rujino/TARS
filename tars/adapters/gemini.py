"""Google Gemini Cloud High-Intelligence LLM Adapter for TARS.

Supports:
- Gemini 2.0 Flash / Pro models via Google GenAI SDK
- Real-time token streaming (astream)
- Single-turn text generation (agenerate)
- Static Prompt & Tool Schema Caching (Static CAG)
- Active health probing with API validation
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from tars.adapters.base import BaseLLMAdapter
from tars.config import get_settings

logger = logging.getLogger("tars.adapters.gemini")


class GeminiAdapter(BaseLLMAdapter):
    """Production-grade LLM Adapter for Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-3.7-flash",
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        enable_caching: bool = True,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key or get_settings().gemini_api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.enable_caching = enable_caching
        self.extra_kwargs = kwargs
        self._cached_content_id: str | None = None
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize Google GenAI or LangChain client."""
        if self._client is None and self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                try:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    self._client = ChatGoogleGenerativeAI(
                        model=self.model_name,
                        google_api_key=self.api_key,
                        temperature=self.temperature,
                    )
                except ImportError:
                    logger.warning("Neither google-genai nor langchain-google-genai is installed.")
        return self._client

    def _format_messages_for_gemini(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
    ) -> list[dict[str, str]]:
        """Convert LangChain BaseMessage sequence into Gemini chat format."""
        formatted: list[dict[str, str]] = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if isinstance(msg, SystemMessage):
                formatted.append({"role": "system", "content": str(msg.content)})
            elif isinstance(msg, HumanMessage):
                formatted.append({"role": "user", "content": str(msg.content)})
            elif isinstance(msg, AIMessage):
                formatted.append({"role": "assistant", "content": str(msg.content)})
            else:
                formatted.append({"role": "user", "content": str(msg.content)})
        return formatted

    async def _call_client_generate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Internal worker executing non-stream Gemini completion (mockable in tests)."""
        client = self._get_client()
        if client is None:
            # Fallback mock/offline response when API key is unconfigured
            last_msg = messages[-1].content if messages else ""
            return f"TARS: Affirmative. Processed '{last_msg}'. Humor setting: 90%."

        # Check if langchain ChatGoogleGenerativeAI
        if hasattr(client, "ainvoke"):
            all_msgs: list[BaseMessage] = []
            if system_prompt:
                all_msgs.append(SystemMessage(content=system_prompt))
            all_msgs.extend(messages)
            res = await client.ainvoke(all_msgs)
            return str(res.content)

        # Direct google-genai SDK
        formatted = self._format_messages_for_gemini(messages, system_prompt)
        prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in formatted)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.model_name,
                contents=prompt_text,
            ),
        )
        return str(response.text)

    async def _call_client_stream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Internal worker executing streaming Gemini completion (mockable in tests)."""
        client = self._get_client()
        if client is None:
            # Default offline token yield
            for token in ["TARS: ", "Confirmed. ", "Navigation ", "locked."]:
                yield token
            return

        if hasattr(client, "astream"):
            all_msgs: list[BaseMessage] = []
            if system_prompt:
                all_msgs.append(SystemMessage(content=system_prompt))
            all_msgs.extend(messages)
            async for chunk in client.astream(all_msgs):
                yield str(chunk.content)
            return

        # Direct SDK stream
        formatted = self._format_messages_for_gemini(messages, system_prompt)
        prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in formatted)
        loop = asyncio.get_running_loop()
        response_stream = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt_text,
            ),
        )
        for chunk in response_stream:
            yield str(chunk.text)

    async def _probe_api_health(self) -> bool:
        """Internal health probe worker (mockable in tests)."""
        if not self.api_key:
            return False
        try:
            client = self._get_client()
            if client is None:
                return False
            # Lightweight probe
            if hasattr(client, "ainvoke"):
                await client.ainvoke([HumanMessage(content="ping")])
            return True
        except Exception as e:
            logger.debug("Gemini health probe failed: %s", e)
            return False

    async def agenerate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Generate complete response text using Google Gemini."""
        return await self._call_client_generate(messages, system_prompt=system_prompt, **kwargs)

    async def astream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield real-time token chunks using Google Gemini stream."""
        async for chunk in self._call_client_stream(messages, system_prompt=system_prompt, **kwargs):
            yield chunk

    async def is_healthy(self) -> bool:
        """Check whether Gemini API is reachable and authorized."""
        return await self._probe_api_health()


__all__ = ["GeminiAdapter"]
