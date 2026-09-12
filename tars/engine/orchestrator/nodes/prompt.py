"""System prompt construction node for TARS orchestration pipeline."""

from __future__ import annotations

import logging
import re
from typing import Any

from tars.domains.knowledge.spec.schemas import OKFDocument
from tars.domains.persona.prompts import SYSTEM_DIRECTIVE_PRIORITY, TARSPersonaManager
from tars.engine.orchestrator.state import (
    DEFAULT_HONESTY_LEVEL,
    DEFAULT_HUMOR_LEVEL,
    DEFAULT_MODE,
    TARSState,
)

logger = logging.getLogger("tars.engine.orchestrator.nodes.prompt")


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

    client_timezone = str(state.get("client_timezone") or "Asia/Seoul")
    reference_time = state.get("reference_time")

    # 2. Build system prompt using TARSPersonaManager (includes SYSTEM DIRECTIVE PRIORITY & TEMPORAL CONTEXT)
    system_prompt = manager.build_system_prompt(
        humor_level=humor_level,
        honesty_level=honesty_level,
        mode=mode,
        context_docs=sanitized_wikis,
        client_timezone=client_timezone,
        reference_time=reference_time,
    )

    # Ensure system directive priority is present in prompt
    if "[SYSTEM DIRECTIVE PRIORITY]" not in system_prompt:
        system_prompt = f"{SYSTEM_DIRECTIVE_PRIORITY}\n\n{system_prompt}"

    # Return exclusively to state['system_prompt'] (messages list is NOT modified)
    return {"system_prompt": system_prompt}
