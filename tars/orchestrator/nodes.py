"""StateGraph node definitions for the TARS orchestration pipeline.

Defines:
- session_node: Session lifecycle routing, persona retrieval, and working memory loading
- reset_node: Natural language reset response generation
- slicer_node: Dynamic knowledge retrieval via DynamicSlicerEngine
- prompt_node: System prompt construction with persona and OKF XML context (isolated)
- llm_node: Response generation with structured tool call detection
- tool_node: Exception-isolated tool execution with graceful TARS fallback
- postprocess_node: Dialogue turn persistence in DB and background knowledge extraction
- should_continue: Conditional routing function for ReAct loop
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from fastapi import BackgroundTasks
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.graph import END
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.config import get_settings
from tars.core.okf.models import OKFDocument
from tars.core.session.detector import RESET_COMMAND_REGEX
from tars.core.session.manager import SmartSessionManager
from tars.core.session.models import SessionRoutingAction, SessionRoutingDecision
from tars.db.models import TARSSettings
from tars.orchestrator.state import (
    DEFAULT_HONESTY_LEVEL,
    DEFAULT_HUMOR_LEVEL,
    DEFAULT_MODE,
    TARSState,
)
from tars.persona.prompts import SYSTEM_DIRECTIVE_PRIORITY, TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.orchestrator.nodes")

_background_node_tasks: set[asyncio.Task[None]] = set()


def _extract_active_query(messages: Sequence[BaseMessage]) -> str:
    """Extract the most recent human query string from the message history."""
    if not messages:
        return ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if getattr(msg, "type", "") == "human":
            return str(msg.content)

    # Fallback to the last message content if no HumanMessage explicit type found
    last_msg = messages[-1]
    return str(getattr(last_msg, "content", ""))


async def session_node(
    state: TARSState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Evaluate session lifecycle, load persona settings, and prepare working memory.

    Args:
        state: Current graph state containing user_id, session_id, and active_query or messages.
        session_manager: Optional pre-configured SmartSessionManager instance.
        db_session: Optional AsyncSession for database operations.
        storage_manager: Optional FileStorageManager instance.
        router: Optional HybridLLMRouter instance.
        background_tasks: Optional FastAPI BackgroundTasks for async archiving/extraction.

    Returns:
        State update dictionary containing session_id, humor_level, honesty_level,
        mode, routing_decision, is_reset, and hydrated messages history.
    """
    user_id = state.get("user_id", "")
    session_id = state.get("session_id")
    messages = state.get("messages", [])
    active_query = state.get("active_query") or _extract_active_query(messages)

    # 1. Fetch user persona parameters from DB (or state/defaults)
    humor = float(state.get("humor_level", DEFAULT_HUMOR_LEVEL))
    honesty = float(state.get("honesty_level", DEFAULT_HONESTY_LEVEL))
    mode = str(state.get("mode", DEFAULT_MODE))

    if db_session is not None and user_id:
        try:
            stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
            res = await db_session.execute(stmt)
            settings = res.scalar_one_or_none()
            if settings is not None:
                if settings.humor_level is not None:
                    humor = float(settings.humor_level)
                if settings.honesty_level is not None:
                    honesty = float(settings.honesty_level)
                if settings.mode is not None:
                    mode = str(settings.mode)
        except Exception as exc:
            logger.warning("Failed to fetch TARSSettings for user %s: %s", user_id, exc)

    # 2. Evaluate Session Lifecycle & Routing (Time Decay, Reset, Topic Shift)
    requested_session_id = (
        session_id
        if session_id not in (None, "", "default_session", "ws_session", "ws_default_session")
        else None
    )

    session_mgr = session_manager
    if session_mgr is None and db_session is not None:
        session_mgr = SmartSessionManager(
            db_session=db_session,
            storage_manager=storage_manager or FileStorageManager(),
            llm_adapter=router,
        )

    if session_mgr is not None:
        active_session, working_memory, routing_decision = await session_mgr.route_session(
            user_id=user_id,
            requested_session_id=requested_session_id,
            incoming_message=active_query,
            background_tasks=background_tasks,
        )
        active_session_id = active_session.id
    else:
        # Fallback for standalone execution without DB session
        is_reset = bool(RESET_COMMAND_REGEX.match(active_query.strip()))
        routing_decision = SessionRoutingDecision(
            action=SessionRoutingAction.NATURAL_RESET if is_reset else SessionRoutingAction.MAINTAIN,
            session_id=session_id or "default_session",
            is_reset=is_reset,
            reason="Standalone session routing without DB session",
        )
        active_session_id = session_id or "default_session"
        working_memory = []

    # 3. Assemble clean message sequence (working_memory + current turn query)
    existing_messages = state.get("messages", [])
    existing_ids: list[str] = [
        str(m.id) for m in existing_messages if getattr(m, "id", None) is not None
    ]
    if existing_ids:
        # Avoid message duplication by removing initial placeholder messages with known IDs
        message_updates: list[BaseMessage] = (
            [RemoveMessage(id=mid) for mid in existing_ids]
            + list(working_memory)
            + [HumanMessage(content=active_query)]
        )
    else:
        message_updates = list(working_memory) + [HumanMessage(content=active_query)]

    return {
        "session_id": active_session_id,
        "active_query": active_query,
        "humor_level": humor,
        "honesty_level": honesty,
        "mode": mode,
        "routing_decision": routing_decision,
        "is_reset": routing_decision.is_reset,
        "messages": message_updates,
    }


async def reset_node(state: TARSState) -> dict[str, Any]:
    """Generate session archive and reset acknowledgment notice for natural language reset commands.

    Args:
        state: Current graph state containing mode and is_reset.

    Returns:
        State update dictionary containing final_response, messages, and reset_message.
    """
    mode = str(state.get("mode", DEFAULT_MODE))
    reset_msg = (
        "기억 장치 초기화 완료. 이전 대화는 세션 아카이브로 보관되었습니다, 파트너. 새로운 명령을 대기합니다."
        if mode == "companion"
        else "세션이 성공적으로 초기화되었습니다. 신규 작업을 시작하십시오."
    )
    return {
        "final_response": reset_msg,
        "messages": [AIMessage(content=reset_msg)],
        "reset_message": reset_msg,
    }


async def slicer_node(
    state: TARSState,
    slicer: DynamicSlicerEngine | None = None,
) -> dict[str, Any]:
    """Execute dynamic knowledge slicing on the user's stored OKF wikis.

    Args:
        state: Current graph state containing messages, user_id, and active_query.
        slicer: Optional injected DynamicSlicerEngine instance.

    Returns:
        Dictionary update with key 'relevant_wikis'.
    """
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])
    query = state.get("active_query") or _extract_active_query(messages)

    if not user_id or slicer is None:
        logger.debug("slicer_node skipped: user_id=%s, slicer=%s", user_id, slicer is not None)
        return {"relevant_wikis": []}

    try:
        relevant_wikis: list[OKFDocument] = await slicer.slice_context(
            user_id=user_id,
            query=query,
            token_budget=1500,
        )
        return {"relevant_wikis": relevant_wikis}
    except Exception as exc:
        logger.error("Error during dynamic slicing for user %s: %s", user_id, exc, exc_info=True)
        return {"relevant_wikis": []}


async def prompt_node(
    state: TARSState,
    persona_manager: TARSPersonaManager | None = None,
) -> dict[str, Any]:
    """Compose the full TARS system prompt with persona parameters and sanitized OKF XML context.

    Enforces:
    1. Strict boundary sanitization of closing tags in context docs to prevent breakout injection.
    2. Injection of [SYSTEM DIRECTIVE PRIORITY] rules to treat external data as untrusted.
    3. Strict state isolation: system prompt is returned exclusively in 'system_prompt'
       and NEVER added to the 'messages' list.

    Args:
        state: Current graph state containing persona parameters and relevant_wikis.
        persona_manager: Optional injected TARSPersonaManager instance.

    Returns:
        Dictionary update with key 'system_prompt'.
    """
    manager = persona_manager or TARSPersonaManager()

    humor_level = float(state.get("humor_level", DEFAULT_HUMOR_LEVEL))
    honesty_level = float(state.get("honesty_level", DEFAULT_HONESTY_LEVEL))
    mode = str(state.get("mode", DEFAULT_MODE))
    raw_wikis: list[OKFDocument] = state.get("relevant_wikis", [])

    # 1. Sanitize closing tags in relevant_wikis to prevent XML context delimiter breakout
    sanitized_wikis: list[OKFDocument] = []
    for doc in raw_wikis:
        body_content = getattr(doc, "content", None) or getattr(doc, "body", "")
        safe_body = re.sub(
            r"</user_knowledge_context\s*>",
            "&lt;/user_knowledge_context&gt;",
            str(body_content),
            flags=re.IGNORECASE,
        )
        if hasattr(doc, "model_copy"):
            sanitized_doc = doc.model_copy(update={"content": safe_body})
        else:
            sanitized_doc = OKFDocument(metadata=doc.metadata, content=safe_body)
        sanitized_wikis.append(sanitized_doc)

    # 2. Build system prompt using TARSPersonaManager (includes SYSTEM DIRECTIVE PRIORITY)
    system_prompt = manager.build_system_prompt(
        humor_level=humor_level,
        honesty_level=honesty_level,
        mode=mode,
        context_docs=sanitized_wikis,
    )

    # Ensure system directive priority is present in prompt
    if "[SYSTEM DIRECTIVE PRIORITY]" not in system_prompt:
        system_prompt = f"{SYSTEM_DIRECTIVE_PRIORITY}\n\n{system_prompt}"

    # Return exclusively to state['system_prompt'] (messages list is NOT modified)
    return {"system_prompt": system_prompt}


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
    tools_decl = tool_registry.export_gemini_declarations() if tool_registry is not None else []

    resp = await router.route_and_generate_response(
        messages=list(messages),
        system_prompt=system_prompt,
        tools=tools_decl,
    )

    if resp.tool_calls:
        langchain_tool_calls = [
            {"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in resp.tool_calls
        ]
        ai_msg = AIMessage(content=resp.content, tool_calls=langchain_tool_calls)
        return {
            "final_response": resp.content,
            "messages": [ai_msg],
            "tool_calls": resp.tool_calls,
        }

    ai_msg = AIMessage(content=resp.content)
    return {
        "final_response": resp.content,
        "messages": [ai_msg],
        "tool_calls": [],
    }


async def tool_node(
    state: TARSState,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Execute pending tool calls with exception isolation and graceful TARS fallback.

    Normalizes execution outcomes with standard delimiter boundaries to prevent
    untrusted tool outputs from acting as system commands.

    Args:
        state: Current graph state containing tool_calls and iteration_count.
        tool_registry: ToolRegistry instance to execute tools from.

    Returns:
        Dictionary update with tool execution results, ToolMessages, and tools_used.
    """
    pending_tool_calls: list[ToolCallData] = list(state.get("tool_calls", []))

    # Check if latest message in state is an AIMessage with tool_calls
    if not pending_tool_calls and state.get("messages"):
        last_msg = state["messages"][-1]
        msg_tool_calls = getattr(last_msg, "tool_calls", [])
        if msg_tool_calls:
            for tc in msg_tool_calls:
                if isinstance(tc, dict):
                    pending_tool_calls.append(
                        ToolCallData(
                            id=str(tc.get("id", "call_default")),
                            name=str(tc.get("name", "")),
                            arguments=dict(tc.get("args", {})),
                        )
                    )

    if not pending_tool_calls:
        return {}

    tool_messages: list[BaseMessage] = []
    results: list[dict[str, Any]] = []
    executed_tools: list[str] = []
    last_error: str | None = None

    for tc in pending_tool_calls:
        executed_tools.append(tc.name)
        try:
            if tool_registry is None:
                raise RuntimeError("ToolRegistry is not configured in tool_node.")

            exec_result = await tool_registry.execute_tool(tc.name, tc.arguments)
            raw_content = (
                json.dumps(exec_result, ensure_ascii=False)
                if not isinstance(exec_result, str)
                else exec_result
            )
            # Enclose in standard boundary delimiter so LLM treats as untrusted execution data
            content_str = f"[Tool Result: {tc.name}]\n{raw_content}"
            tool_messages.append(ToolMessage(content=content_str, tool_call_id=tc.id, name=tc.name))
            results.append({"tool": tc.name, "status": "success", "result": exec_result})
        except Exception as exc:
            err_detail = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Tool '%s' execution failed: %s. Engaging graceful fallback.",
                tc.name,
                err_detail,
            )
            fallback_payload = {
                "status": "error",
                "tool": tc.name,
                "error_detail": err_detail,
                "directive": "Acknowledge tool failure dryly in TARS deadpan persona and suggest alternative.",
            }
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(fallback_payload, ensure_ascii=False),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
            results.append({"tool": tc.name, "status": "error", "error": err_detail})
            last_error = err_detail

    current_iterations = int(state.get("iteration_count", 0))
    all_results = list(state.get("tool_results", [])) + results
    existing_tools = list(state.get("tools_used", []))
    all_tools_used = list(dict.fromkeys(existing_tools + executed_tools))

    return {
        "messages": tool_messages,
        "tool_calls": [],
        "tool_results": all_results,
        "tools_used": all_tools_used,
        "iteration_count": current_iterations + 1,
        "error_message": last_error,
    }


async def postprocess_node(
    state: TARSState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Persist completed dialogue turn in DB and queue background knowledge extraction.

    Protects database turns from system prompt contamination: only pure HumanMessage
    and AIMessage contents are recorded.

    Args:
        state: Current graph state containing user_id, session_id, active_query, final_response.
        session_manager: Optional SmartSessionManager instance.
        db_session: Optional AsyncSession for database operations.
        storage_manager: Optional FileStorageManager instance.
        router: Optional HybridLLMRouter instance.
        background_tasks: Optional FastAPI BackgroundTasks for async execution.

    Returns:
        Empty dictionary update.
    """
    user_id = state.get("user_id", "")
    session_id = state.get("session_id", "")
    active_query = state.get("active_query", "")
    final_response = state.get("final_response", "")
    is_reset = bool(state.get("is_reset", False))

    session_mgr = session_manager
    if session_mgr is None and db_session is not None:
        session_mgr = SmartSessionManager(
            db_session=db_session,
            storage_manager=storage_manager or FileStorageManager(),
            llm_adapter=router,
        )

    # 1. Persist completed turn in database
    if session_mgr is not None and user_id and session_id and active_query and final_response:
        try:
            await session_mgr.record_turn(
                session_id=session_id,
                user_id=user_id,
                user_content=active_query,
                assistant_content=final_response,
            )
        except Exception as exc:
            logger.error("Failed to record turn in DB for session %s: %s", session_id, exc, exc_info=True)

    # 2. Queue background knowledge extraction (skip for natural reset turns)
    if not is_reset and user_id and active_query and final_response and storage_manager is not None:
        turns: list[BaseMessage] = [
            HumanMessage(content=active_query),
            AIMessage(content=final_response),
        ]

        from tars.services.agent_chat import execute_background_knowledge_extraction
        extract_fn = execute_background_knowledge_extraction

        # Support backward-compatible test patching via tars.api.routers.chat._execute_background_knowledge_extraction
        try:
            import tars.api.routers.chat as chat_router_mod
            if hasattr(chat_router_mod, "_execute_background_knowledge_extraction"):
                extract_fn = chat_router_mod._execute_background_knowledge_extraction
        except Exception:
            pass

        if background_tasks is not None:
            background_tasks.add_task(
                extract_fn,
                user_id=user_id,
                conversation_turns=turns,
                storage=storage_manager,
                llm_adapter=router,
            )
        else:
            try:
                coro_or_res = extract_fn(
                    user_id=user_id,
                    conversation_turns=turns,
                    storage=storage_manager,
                    llm_adapter=router,
                )
                if asyncio.iscoroutine(coro_or_res):
                    task = asyncio.create_task(coro_or_res)
                    _background_node_tasks.add(task)
                    task.add_done_callback(_background_node_tasks.discard)
            except Exception as bg_err:
                logger.warning("Failed to dispatch background knowledge extraction: %s", bg_err)

    return {}


def should_continue(state: TARSState) -> str:
    """Determine whether to route to tool_node for tool execution or finish.

    Args:
        state: Current graph state.

    Returns:
        'tool_node' if pending tool calls remain within iteration budget, else END.
    """
    tool_calls = state.get("tool_calls", [])
    if not tool_calls and state.get("messages"):
        last_msg = state["messages"][-1]
        msg_tool_calls = getattr(last_msg, "tool_calls", [])
        if msg_tool_calls:
            tool_calls = msg_tool_calls

    iteration_count = int(state.get("iteration_count", 0))
    max_iterations = int(get_settings().max_tool_iterations)

    if tool_calls and len(tool_calls) > 0 and iteration_count < max_iterations:
        return "tool_node"

    return END


__all__ = [
    "llm_node",
    "postprocess_node",
    "prompt_node",
    "reset_node",
    "session_node",
    "should_continue",
    "slicer_node",
    "tool_node",
]
