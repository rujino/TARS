"""Dynamic knowledge slicing node for TARS orchestration pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tars.engine.orchestrator.nodes.session import _extract_active_query
from tars.engine.orchestrator.state import TARSState

if TYPE_CHECKING:
    from tars.domains.knowledge.slicer.engine import DynamicSlicerEngine
    from tars.domains.knowledge.spec.schemas import OKFDocument

logger = logging.getLogger("tars.engine.orchestrator.nodes.slicer")


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
