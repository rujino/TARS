"""Langfuse observability and tracing integration for TARS Agent pipeline.

Provides safe, optional CallbackHandler construction and trace attribute propagation
without impacting agent execution if Langfuse is disabled or unavailable.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import types
from collections.abc import Iterator
from typing import Any

from tars.config import get_settings

logger = logging.getLogger("tars.orchestrator.observability")


def _ensure_langchain_compat_shims() -> None:
    """Ensure Langfuse 2.x callback can import langchain legacy modules from langchain_core."""
    import langchain_core.agents
    import langchain_core.callbacks.base
    import langchain_core.documents

    if "langchain.callbacks" not in sys.modules:
        lc_callbacks = types.ModuleType("langchain.callbacks")
        lc_callbacks_base = types.ModuleType("langchain.callbacks.base")
        setattr(
            lc_callbacks_base,
            "BaseCallbackHandler",
            langchain_core.callbacks.base.BaseCallbackHandler,
        )
        setattr(lc_callbacks, "base", lc_callbacks_base)
        sys.modules["langchain.callbacks"] = lc_callbacks
        sys.modules["langchain.callbacks.base"] = lc_callbacks_base

    if "langchain.schema" not in sys.modules:
        lc_schema = types.ModuleType("langchain.schema")
        lc_schema_agent = types.ModuleType("langchain.schema.agent")
        setattr(lc_schema_agent, "AgentAction", langchain_core.agents.AgentAction)
        setattr(lc_schema_agent, "AgentFinish", langchain_core.agents.AgentFinish)
        setattr(lc_schema, "agent", lc_schema_agent)

        lc_schema_doc = types.ModuleType("langchain.schema.document")
        setattr(lc_schema_doc, "Document", langchain_core.documents.Document)
        setattr(lc_schema, "document", lc_schema_doc)

        sys.modules["langchain.schema"] = lc_schema
        sys.modules["langchain.schema.agent"] = lc_schema_agent
        sys.modules["langchain.schema.document"] = lc_schema_doc


def get_langfuse_callback_handler(
    user_id: str,
    session_id: str,
    tags: list[str] | None = None,
) -> Any | None:
    """Create a Langfuse CallbackHandler if Langfuse is enabled and configured.

    Returns None if Langfuse is disabled or credentials are missing, ensuring
    graceful degradation.
    """
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning(
            "Langfuse is enabled in settings, but LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is empty. Skipping tracing."
        )
        return None

    try:
        # Set environment variables for Langfuse client if not already present
        if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
            os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        if not os.environ.get("LANGFUSE_SECRET_KEY"):
            os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        if not os.environ.get("LANGFUSE_HOST"):
            os.environ["LANGFUSE_HOST"] = settings.langfuse_host

        _ensure_langchain_compat_shims()
        from langfuse.callback import CallbackHandler

        merged_tags = ["tars", "agent"]
        if tags:
            merged_tags.extend(tags)

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            user_id=user_id,
            session_id=session_id,
            tags=merged_tags,
        )
        return handler
    except Exception as exc:
        logger.error("Failed to initialize Langfuse CallbackHandler: %s", exc, exc_info=True)
        return None


def flush_langfuse_handler(
    handler: Any | None,
    engine: str | None = None,
    model_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Flush pending traces from the given callback handler and tag the responding engine/model."""
    if handler is None:
        return

    try:
        if hasattr(handler, "trace") and handler.trace is not None:
            existing_tags = list(getattr(handler, "tags", []) or [])
            new_tags = list(existing_tags)
            if engine:
                new_tags.append(f"engine:{engine.lower()}")
            if model_name:
                new_tags.append(f"model:{model_name}")

            trace_meta = dict(getattr(handler, "metadata", {}) or {})
            if engine:
                trace_meta["engine"] = engine.upper()
            if model_name:
                trace_meta["model_name"] = model_name
            if metadata:
                trace_meta.update(metadata)

            handler.trace.update(
                tags=list(dict.fromkeys(new_tags)),
                metadata=trace_meta,
            )
        if hasattr(handler, "flush") and callable(handler.flush):
            handler.flush()
    except Exception as exc:
        logger.debug("Failed to flush Langfuse handler: %s", exc)


@contextlib.contextmanager
def trace_attributes_context(
    user_id: str,
    session_id: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Context manager to propagate user_id, session_id, tags to the current trace.

    Falls back to a no-op context manager when Langfuse is disabled.
    """
    settings = get_settings()
    if not settings.langfuse_enabled or not settings.langfuse_public_key:
        yield
        return

    try:
        from langfuse import propagate_attributes

        merged_tags = ["tars", "agent"]
        if tags:
            merged_tags.extend(tags)

        with propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            tags=merged_tags,
            metadata=metadata or {},
        ):
            yield
    except Exception as exc:
        logger.debug("Error propagating Langfuse attributes (continuing gracefully): %s", exc)
        yield


__all__ = [
    "get_langfuse_callback_handler",
    "flush_langfuse_handler",
    "trace_attributes_context",
]
