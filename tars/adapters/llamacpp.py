"""Local llama.cpp (SLM) Adapter for TARS.

Supports:
- OpenAI-compatible /v1/chat/completions HTTP REST endpoint
- Real-time token streaming via Server-Sent Events (SSE)
- Strict 500ms fast health probe with timeout enforcement
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from tars.adapters.base import BaseLLMAdapter, LLMResponse, ToolCallData
from tars.config import get_settings

logger = logging.getLogger("tars.adapters.llamacpp")


class LlamaCppAdapter(BaseLLMAdapter):
    """Production-grade LLM Adapter for local llama.cpp / llama-server."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_ms: int = 500,
        model_name: str | None = None,
        temperature: float = 0.7,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.llamacpp_base_url).rstrip("/")
        self.timeout_ms = timeout_ms
        self.timeout_sec = timeout_ms / 1000.0
        self.model_name = model_name or settings.llamacpp_model_name
        self.temperature = temperature
        self._client = client

    def _get_http_client(self) -> httpx.AsyncClient:
        """Obtain or instantiate an AsyncClient with default timeout."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=10.0)
            )
        return self._client

    def _format_messages_for_slm(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
    ) -> list[dict[str, str]]:
        """Format LangChain messages into standard OpenAI chat format."""
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

    async def _http_post_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Internal HTTP POST worker for structured response with tool calling (mockable in tests)."""
        client = self._get_http_client()
        url = (
            f"{self.base_url}/chat/completions"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/chat/completions"
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._format_messages_for_slm(messages, system_prompt),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": False,
        }
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        response = await client.post(url, json=payload, timeout=max(self.timeout_sec * 6.0, 30.0))
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if not choices or "message" not in choices[0]:
            return LLMResponse(content="", tool_calls=[], model_name=self.model_name)

        msg = choices[0]["message"]
        content = str(msg.get("content", "") or "")
        raw_tool_calls = msg.get("tool_calls", [])

        parsed_tool_calls: list[ToolCallData] = []
        if raw_tool_calls:
            for tc in raw_tool_calls:
                tc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                fn = tc.get("function", {})
                name = fn.get("name") or tc.get("name", "")
                raw_args = fn.get("arguments", {}) if "function" in tc else tc.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                parsed_tool_calls.append(
                    ToolCallData(id=tc_id, name=name, arguments=args)
                )

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            model_name=self.model_name,
        )

    async def _http_post_completion(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Internal HTTP POST worker for full text generation (mockable in tests)."""
        resp = await self._http_post_response(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        )
        return resp.content

    async def _http_stream_completion(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Internal HTTP streaming worker for SSE tokens (mockable in tests)."""
        client = self._get_http_client()
        url = (
            f"{self.base_url}/chat/completions"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/chat/completions"
        )
        payload = {
            "model": self.model_name,
            "messages": self._format_messages_for_slm(messages, system_prompt),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        async with client.stream(
            "POST", url, json=payload, timeout=max(self.timeout_sec * 6.0, 60.0)
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                clean_line = line.strip()
                if not clean_line or not clean_line.startswith("data:"):
                    continue
                data_str = clean_line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content_delta = delta.get("content", "")
                    if content_delta:
                        yield content_delta
                except json.JSONDecodeError:
                    continue

    async def _probe_endpoint_health(self) -> bool:
        """Internal health probe worker connecting to local server (mockable in tests)."""
        client = self._get_http_client()
        root_url = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        v1_url = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

        probe_urls = [
            f"{root_url}/health",
            f"{v1_url}/health",
            f"{v1_url}/models",
            f"{root_url}/models",
        ]
        for url in probe_urls:
            try:
                res = await client.get(url, timeout=self.timeout_sec)
                if res.status_code in (200, 204):
                    return True
            except Exception:
                continue
        return False

    async def agenerate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate structured response with parsed tool calls via local SLM."""
        return await self._http_post_response(messages, system_prompt=system_prompt, **kwargs)

    async def agenerate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Generate single completion text via local SLM."""
        return await self._http_post_completion(messages, system_prompt=system_prompt, **kwargs)

    async def astream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream token chunks from local SLM via SSE."""
        async for chunk in self._http_stream_completion(
            messages, system_prompt=system_prompt, **kwargs
        ):
            yield chunk

    async def is_healthy(self) -> bool:
        """Probe local SLM server health with strict timeout enforcement."""
        try:
            return await asyncio.wait_for(
                self._probe_endpoint_health(),
                timeout=self.timeout_sec,
            )
        except Exception:
            return False


__all__ = ["LlamaCppAdapter"]
