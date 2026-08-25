"""StateGraph node definitions for the TARS orchestration pipeline.

Defines slicer_node, prompt_node, llm_node, and tool_node with strict type annotations.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from tars.adapters.router import HybridLLMRouter
from tars.core.okf.models import OKFDocument
from tars.orchestrator.state import (
    DEFAULT_HONESTY_LEVEL,
    DEFAULT_HUMOR_LEVEL,
    DEFAULT_MODE,
    TARSState,
)
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine

logger = logging.getLogger("tars.orchestrator.nodes")


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


async def slicer_node(
    state: TARSState,
    slicer: DynamicSlicerEngine | None = None,
) -> dict[str, Any]:
    """Execute dynamic knowledge slicing on the user's stored OKF wikis.

    Extracts user query from message history and queries DynamicSlicerEngine
    within a default token budget of 1500 tokens.

    Args:
        state: Current graph state containing messages and user_id.
        slicer: Optional injected DynamicSlicerEngine instance.

    Returns:
        Dictionary update with key 'relevant_wikis'.
    """
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])
    query = _extract_active_query(messages)

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
    """Compose the full TARS system prompt with persona parameters and OKF XML context.

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
    relevant_wikis: list[OKFDocument] = state.get("relevant_wikis", [])

    system_prompt = manager.build_system_prompt(
        humor_level=humor_level,
        honesty_level=honesty_level,
        mode=mode,
        context_docs=relevant_wikis,
    )

    return {"system_prompt": system_prompt}


async def llm_node(
    state: TARSState,
    router: HybridLLMRouter | None = None,
) -> dict[str, Any]:
    """Invoke the Hybrid LLM Router to generate and stream the assistant response.

    Accumulates tokens from the streaming router, constructs an AIMessage,
    and returns state updates.

    Args:
        state: Current graph state containing messages and system_prompt.
        router: Optional injected HybridLLMRouter instance.

    Returns:
        Dictionary update with keys 'final_response' and 'messages' ([AIMessage]).
    """
    if router is None:
        raise ValueError("HybridLLMRouter must be provided to llm_node.")

    messages = state.get("messages", [])
    system_prompt = state.get("system_prompt", "")

    # Execute stream and accumulate full response
    chunks: list[str] = []
    async for chunk in router.route_and_stream(
        messages=list(messages),
        system_prompt=system_prompt,
    ):
        chunks.append(chunk)

    final_text = "".join(chunks)
    ai_message = AIMessage(content=final_text)

    return {
        "final_response": final_text,
        "messages": [ai_message],
    }


async def tool_node(
    state: TARSState,
    tool_registry: Any | None = None,
) -> dict[str, Any]:
    """Execute pending tool calls if requested by the LLM (extension hook)."""
    return {}


__all__ = [
    "llm_node",
    "prompt_node",
    "slicer_node",
    "tool_node",
]
