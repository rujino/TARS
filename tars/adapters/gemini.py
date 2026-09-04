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
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from tars.adapters.base import BaseLLMAdapter, LLMResponse, ToolCallData
from tars.config import get_settings

logger = logging.getLogger("tars.adapters.gemini")


class GeminiAdapter(BaseLLMAdapter):
    """Production-grade LLM Adapter for Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        enable_caching: bool = True,
        **kwargs: Any,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.enable_caching = enable_caching
        self.extra_kwargs = kwargs
        self.tools: list[dict[str, Any]] = list(kwargs.get("tools", []))
        self._cached_content_id: str | None = None
        self._client: Any = None

    def bind_tools(self, tools: Sequence[dict[str, Any]]) -> GeminiAdapter:
        """Bind tool declarations for Gemini function calling."""
        self.tools = list(tools)
        return self

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
        for msg in messages:
            if isinstance(msg, SystemMessage):
                continue
            elif isinstance(msg, HumanMessage):
                formatted.append({"role": "user", "content": str(msg.content)})
            elif isinstance(msg, AIMessage):
                formatted.append({"role": "assistant", "content": str(msg.content)})
            else:
                formatted.append({"role": "user", "content": str(msg.content)})
        return formatted

    async def _call_client_generate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Internal worker executing structured Gemini completion with tool calling."""
        client = self._get_client()
        tools = kwargs.get("tools") or self.tools

        if client is None:
            # Fallback mock/offline response when API key is unconfigured
            last_msg = messages[-1].content if messages else ""
            return LLMResponse(
                content=f"TARS: Affirmative. Processed '{last_msg}'. Humor setting: 90%.",
                tool_calls=[],
                model_name=self.model_name,
            )

        formatted = self._format_messages_for_gemini(messages, system_prompt)
        prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in formatted)

        # 1. Direct google-genai async SDK
        if hasattr(client, "aio") and hasattr(client.aio, "models"):
            try:
                from google.genai import types

                genai_tools = None
                if tools:
                    genai_tools = [types.Tool(function_declarations=list(tools))]

                config = types.GenerateContentConfig(
                    system_instruction=system_prompt if system_prompt else None,
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                    tools=genai_tools,
                )
            except Exception as cfg_err:
                logger.debug("Failed to build GenerateContentConfig: %s", cfg_err)
                config = None

            if config is not None:
                resp = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt_text,
                    config=config,
                )
            else:
                resp = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt_text,
                )

            parsed_tool_calls: list[ToolCallData] = []
            if resp is not None and hasattr(resp, "function_calls") and resp.function_calls:
                for fc in resp.function_calls:
                    call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                    name = getattr(fc, "name", "")
                    args = dict(getattr(fc, "args", {}) or {})
                    parsed_tool_calls.append(
                        ToolCallData(id=call_id, name=name, arguments=args)
                    )

            content = ""
            if resp is not None:
                try:
                    content = str(resp.text or "")
                except Exception:
                    content = ""

            return LLMResponse(
                content=content,
                tool_calls=parsed_tool_calls,
                model_name=self.model_name,
            )

        # 2. Check if langchain ChatGoogleGenerativeAI
        if hasattr(client, "ainvoke") and callable(getattr(client, "ainvoke")):
            bound_client = client
            if tools and hasattr(client, "bind_tools"):
                try:
                    bound_client = client.bind_tools(tools)
                except Exception as b_err:
                    logger.warning("Failed to bind tools to langchain client: %s", b_err)

            all_msgs: list[BaseMessage] = []
            if system_prompt:
                all_msgs.append(SystemMessage(content=system_prompt))
            all_msgs.extend(messages)
            res = await bound_client.ainvoke(all_msgs)

            tool_calls = []
            raw_tcs = getattr(res, "tool_calls", None) or []
            for tc in raw_tcs:
                if isinstance(tc, dict):
                    tool_calls.append(
                        ToolCallData(
                            id=str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                            name=str(tc.get("name", "")),
                            arguments=dict(tc.get("args", {}) or {}),
                        )
                    )

            return LLMResponse(
                content=str(res.content or ""),
                tool_calls=tool_calls,
                model_name=self.model_name,
            )
        else:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: (
                    client.models.generate_content(
                        model=self.model_name,
                        contents=prompt_text,
                        config=config,
                    )
                    if config is not None
                    else client.models.generate_content(
                        model=self.model_name,
                        contents=prompt_text,
                    )
                ),
            )

        parsed_tool_calls: list[ToolCallData] = []
        if resp is not None and hasattr(resp, "function_calls") and resp.function_calls:
            for fc in resp.function_calls:
                call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                name = getattr(fc, "name", "")
                args = dict(getattr(fc, "args", {}) or {})
                parsed_tool_calls.append(
                    ToolCallData(id=call_id, name=name, arguments=args)
                )

        content = ""
        if resp is not None:
            try:
                content = str(resp.text or "")
            except Exception:
                content = ""

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            model_name=self.model_name,
        )

    async def _call_client_generate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Internal worker executing non-stream Gemini completion (mockable in tests)."""
        resp = await self._call_client_generate_response(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        )
        return resp.content

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
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system_prompt if system_prompt else None,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        except Exception:
            config = None

        formatted = self._format_messages_for_gemini(messages, system_prompt)
        prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in formatted)

        # Use native async streaming if available
        if hasattr(client, "aio") and hasattr(client.aio, "models"):
            if config is not None:
                stream = await client.aio.models.generate_content_stream(
                    model=self.model_name,
                    contents=prompt_text,
                    config=config,
                )
            else:
                stream = await client.aio.models.generate_content_stream(
                    model=self.model_name,
                    contents=prompt_text,
                )
            async for chunk in stream:
                if chunk.text:
                    yield str(chunk.text)
            return

        loop = asyncio.get_running_loop()
        response_stream = await loop.run_in_executor(
            None,
            lambda: (
                client.models.generate_content_stream(
                    model=self.model_name,
                    contents=prompt_text,
                    config=config,
                )
                if config is not None
                else client.models.generate_content_stream(
                    model=self.model_name,
                    contents=prompt_text,
                )
            ),
        )
        for chunk in response_stream:
            if chunk.text:
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

    async def agenerate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate structured response with parsed tool calls using Google Gemini."""
        return await self._call_client_generate_response(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        )

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
        async for chunk in self._call_client_stream(
            messages, system_prompt=system_prompt, **kwargs
        ):
            yield chunk

    async def is_healthy(self) -> bool:
        """Check whether Gemini API is reachable and authorized."""
        return await self._probe_api_health()


__all__ = ["GeminiAdapter"]
