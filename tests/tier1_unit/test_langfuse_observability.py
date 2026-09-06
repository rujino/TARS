import pytest
from unittest.mock import MagicMock

from tars.orchestrator.observability import (
    get_langfuse_callback_handler,
    trace_attributes_context,
)
from tars.orchestrator.stream_bridge import LangGraphStreamBridge
from tars.orchestrator.models import AgentStreamEvent


def test_langfuse_handler_when_disabled(monkeypatch):
    """Should return None when langfuse is disabled."""
    monkeypatch.setenv("TARS_LANGFUSE_ENABLED", "false")
    from tars.config import get_settings
    get_settings.cache_clear()

    handler = get_langfuse_callback_handler("test_user", "test_session")
    assert handler is None


def test_langfuse_handler_when_keys_missing(monkeypatch):
    """Should return None when enabled but keys are missing."""
    monkeypatch.setenv("TARS_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("TARS_LANGFUSE_PUBLIC_KEY", "")
    from tars.config import get_settings
    get_settings.cache_clear()

    handler = get_langfuse_callback_handler("test_user", "test_session")
    assert handler is None


def test_trace_attributes_context_disabled(monkeypatch):
    """Context manager should yield without error when disabled."""
    monkeypatch.setenv("TARS_LANGFUSE_ENABLED", "false")
    from tars.config import get_settings
    get_settings.cache_clear()

    with trace_attributes_context("test_user", "test_session"):
        pass  # should not raise


@pytest.mark.asyncio
async def test_stream_graph_events_passes_config():
    """Verify that LangGraphStreamBridge passes config to astream_events."""
    mock_graph = MagicMock()

    async def dummy_events(*args, **kwargs):
        assert kwargs.get("version") == "v2"
        assert kwargs.get("config") == {"callbacks": ["dummy_callback"]}
        yield {"event": "on_chain_end", "name": "session_node", "data": {"output": {"session_id": "s123"}}}
        yield {"event": "on_custom_event", "name": "done", "data": {}}

    mock_graph.astream_events = dummy_events

    events: list[AgentStreamEvent] = []
    async for ev in LangGraphStreamBridge.stream_graph_events(
        graph=mock_graph,
        initial_state={"user_id": "u1", "session_id": "s123"},
        config={"callbacks": ["dummy_callback"]},
    ):
        events.append(ev)

    assert any(e.type == "stream_start" for e in events)
