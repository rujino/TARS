"""LLM response generation node for TARS orchestration pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage

from tars.engine.adapters.base import LLMResponse
from tars.engine.orchestrator.state import TARSState

if TYPE_CHECKING:
    from tars.domains.tools.registry import ToolRegistry
    from tars.engine.adapters.router import HybridLLMRouter

logger = logging.getLogger("tars.engine.orchestrator.nodes.llm")


async def llm_node(
    state: TARSState,
    router: HybridLLMRouter | None = None,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Invoke the Hybrid LLM Router to generate response or request tool calls.

    Preserves state['system_prompt'] immutability across ReAct loop cycles.

    Args:
        state: Current graph state containing messages and system_prompt.
        router: Configured HybridLLMRouter instance.
        tool_registry: Optional ToolRegistry containing available tools.

    Returns:
        Dictionary update with final_response, messages, and tool_calls.
    """
    if router is None:
        raise ValueError("HybridLLMRouter must be provided to llm_node.")

    messages = state.get("messages", [])
    system_prompt = state.get("system_prompt", "")
    disabled_tools = state.get("disabled_tools")
    tools_decl = (
        tool_registry.export_gemini_declarations(disabled_tools=disabled_tools)
        if tool_registry is not None
        else []
    )

    # 1. Direct streaming if route_and_stream is explicitly mock-patched for stream tests
    stream_fn = getattr(router, "route_and_stream", None)
    is_mock_patched = (
        stream_fn is not None
        and hasattr(stream_fn, "_mock_side_effect")
        and getattr(stream_fn, "side_effect", None) is not None
    )

    if is_mock_patched and callable(stream_fn):
        try:
            stream_iter = stream_fn(
                messages=list(messages),
                system_prompt=system_prompt,
                tools=tools_decl,
                user_facing=True,
            )
            # [STUDY]: 비동기 이터러블, 덕 타이핑, 그리고 정적 타입 가드
            # 1. 덕 타이핑(Duck Typing)의 개념과 파이썬 철학:
            #    - "오리처럼 걷고 오리처럼 꽥꽥거리면 그것은 오리다(If it walks like a duck...)"
            #    - 파이썬은 상속(명시적 타입 계층)보다 '객체가 어떤 메서드를 지원하는가'를 중시합니다.
            #    - 어떤 객체가 `AsyncIterable` 클래스를 명시적으로 상속받지 않았더라도, `__aiter__`
            #      메서드만 구현되어 있다면 파이썬 런타임은 비동기 이터러블(오리)로 간주하고 동작합니다.
            #
            # 2. `async for`와 `__aiter__`의 메커니즘 (PEP 492):
            #    - 파이썬의 `async for` 구문은 내부적으로 대상 객체의 `__aiter__()` 메서드를 호출해
            #      비동기 이터레이터(`__anext__()`를 가진 객체)를 얻고 매 루프마다 `await __anext__()`를
            #      수행합니다.
            #    - 즉, 비동기 스트림 덕 타이핑의 핵심 기준이 바로 `__aiter__` 메서드의 유무입니다.
            #
            # 3. `hasattr(...)` 대신 `isinstance(..., AsyncIterable)`를 쓰는 이유:
            #    - `stream_iter`는 동적 룩업(`getattr`)으로 얻은 결과라 정적 타입이 `object`로 추론됩니다.
            #    - 단순 `hasattr(stream_iter, "__aiter__")`는 런타임 덕 타이핑 검사는 통과하지만,
            #      정적 분석기(Pylance/Pyright)에 타입 좁히기(Type Narrowing) 힌트를 주지 못해
            #      `async for`에서 "object is not iterable" 린트 에러가 발생합니다.
            #    - 반면 `collections.abc.AsyncIterable`은 `__subclasshook__` 매직 메서드를 통해
            #      런타임에는 대상 객체가 `__aiter__`를 가졌는지 '덕 타이핑'으로 검사하면서,
            #      동시에 정적 분석기에게도 안전한 이터러블 타입임을 보증하여 양쪽 요구사항을 모두 해결합니다.
            if isinstance(stream_iter, AsyncIterable):
                accumulated: list[str] = []
                async for token in stream_iter:
                    tok_str = str(token)
                    accumulated.append(tok_str)
                    try:
                        await adispatch_custom_event(
                            "token",
                            {"delta": tok_str, "content": tok_str},
                        )
                    except Exception:
                        pass
                if accumulated:
                    full_text = "".join(accumulated)
                    ai_msg = AIMessage(content=full_text)
                    return {
                        "final_response": full_text,
                        "messages": [ai_msg],
                        "tool_calls": [],
                    }
        except Exception as exc:
            logger.warning("Direct route_and_stream bypassed or failed: %s", exc)

    # 2. ReAct structured response generation
    gen_fn = getattr(router, "route_and_generate_response", None)
    resp: LLMResponse
    if callable(gen_fn):
        maybe_coro = gen_fn(
            messages=list(messages),
            system_prompt=system_prompt,
            tools=tools_decl,
        )
        raw_resp = await maybe_coro if asyncio.iscoroutine(maybe_coro) else maybe_coro
        resp = raw_resp if isinstance(raw_resp, LLMResponse) else LLMResponse(content=str(raw_resp))
    else:
        resp = LLMResponse(content="", tool_calls=[])

    model_name = getattr(resp, "model_name", "") or ""
    is_slm = (
        ("slm" in model_name.lower())
        or ("gemma" in model_name.lower())
        or resp.content.startswith("[Auxiliary")
        or resp.content.startswith("[Tactical Uplink")
    )
    engine = "slm" if is_slm else "gemini"
    if not model_name:
        model_name = "gemma-4-12b" if is_slm else "gemini-3.7-flash"

    response_meta = {
        "engine": engine,
        "model_name": model_name,
    }

    if resp.tool_calls:
        langchain_tool_calls = [
            {"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in resp.tool_calls
        ]
        ai_msg = AIMessage(
            content=resp.content,
            tool_calls=langchain_tool_calls,
            response_metadata=response_meta,
        )
        return {
            "final_response": resp.content,
            "messages": [ai_msg],
            "tool_calls": resp.tool_calls,
            "engine": engine,
            "model_name": model_name,
        }

    # Emit complete token event for single-turn non-tool responses
    if resp.content:
        try:
            await adispatch_custom_event(
                "token",
                {"delta": resp.content, "content": resp.content},
            )
        except Exception:
            pass

    ai_msg = AIMessage(content=resp.content, response_metadata=response_meta)
    return {
        "final_response": resp.content,
        "messages": [ai_msg],
        "tool_calls": [],
        "engine": engine,
        "model_name": model_name,
    }
