"""Tier 3 E2E API Tests: Server-Sent Events (SSE) Real-Time Token Streaming (POST /api/v1/chat/stream).

Verifies:
1. Endpoint Protocol Compliance:
   - Responds with HTTP 200 and Content-Type: text/event-stream (or containing text/event-stream).
2. SSE Event Stream Formatting:
   - Verifies sequential events:
     - event: stream_start
     - event: token
     - event: stream_end
     - event: done (data: [DONE])
3. Payload Content & Token Reassembly:
   - Validates that streamed tokens match the mock LLM output.
4. Security & Error Handling:
   - Rejects unauthenticated requests with 401 Unauthorized.
   - Rejects empty message bodies with 422 Unprocessable Entity.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tars.adapters.router import HybridLLMRouter
from tars.db.models import User

# ============================================================================
# Helper Functions for SSE Parsing
# ============================================================================


def parse_sse_events(raw_sse_text: str) -> list[dict[str, str]]:
    """Parse raw HTTP SSE stream body into a list of event/data dictionaries."""
    events: list[dict[str, str]] = []
    blocks = raw_sse_text.strip().split("\n\n")

    for block in blocks:
        if not block.strip():
            continue
        event_dict: dict[str, str] = {}
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("event:"):
                event_dict["event"] = line.replace("event:", "", 1).strip()
            elif line.startswith("data:"):
                event_dict["data"] = line.replace("data:", "", 1).strip()
        if event_dict:
            events.append(event_dict)

    return events


# ============================================================================
# 1. SSE Streaming Happy Path Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sse_streaming_happy_path(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify POST /api/v1/chat/stream delivers valid SSE token stream."""
    mock_tokens = ["TARS: ", "Navigation ", "thrusters ", "online."]

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream):
        payload = {
            "session_id": "session_sse_001",
            "message": "TARS, thruster status?",
        }

        response = await auth_client.post("/api/v1/chat/stream", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        raw_content = response.text
        events = parse_sse_events(raw_content)

        # 1. Verify event types present
        event_names = [e.get("event") for e in events if "event" in e]
        assert "stream_start" in event_names
        assert "token" in event_names
        assert "stream_end" in event_names or "done" in event_names

        # 2. Extract tokens and verify reassembly
        token_pieces: list[str] = []
        for e in events:
            if e.get("event") == "token":
                try:
                    data_obj = json.loads(e["data"])
                    token_pieces.append(data_obj.get("content") or data_obj.get("delta", ""))
                except json.JSONDecodeError:
                    token_pieces.append(e["data"])

        assert "".join(token_pieces) == "TARS: Navigation thrusters online."


# ============================================================================
# 2. SSE Error Handling & Access Control Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sse_streaming_unauthenticated(
    api_client: AsyncClient,
) -> None:
    """Verify unauthenticated SSE stream request returns 401."""
    payload = {
        "session_id": "session_unauth",
        "message": "Hello",
    }
    response = await api_client.post("/api/v1/chat/stream", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sse_streaming_empty_message_validation(
    auth_client: AsyncClient,
) -> None:
    """Verify empty message body returns 422 Unprocessable Entity."""
    response = await auth_client.post("/api/v1/chat/stream", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sse_stream_terminates_on_client_disconnect(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify POST /api/v1/chat/stream terminates immediately when request.is_disconnected() is True."""
    mock_tokens = ["TARS: ", "Navigation ", "thrusters ", "online."]

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    # Simulate client disconnect after the first token event
    # First 2 calls (stream_start, first token) return False; subsequent call returns True
    disconnect_sequence = [False, False, True, True]

    async def mock_is_disconnected(self: Any) -> bool:
        if disconnect_sequence:
            return disconnect_sequence.pop(0)
        return True

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream), \
         patch("starlette.requests.Request.is_disconnected", new=mock_is_disconnected), \
         patch("tars.api.routers.chat.logger.info") as mock_log_info:
        payload = {
            "session_id": "session_disconnect_001",
            "message": "TARS, status?",
        }
        response = await auth_client.post("/api/v1/chat/stream", json=payload)
        assert response.status_code == 200

        raw_content = response.text
        events = parse_sse_events(raw_content)

        # Extract tokens
        token_pieces: list[str] = []
        for e in events:
            if e.get("event") == "token":
                try:
                    data_obj = json.loads(e["data"])
                    token_pieces.append(data_obj.get("content") or data_obj.get("delta", ""))
                except json.JSONDecodeError:
                    token_pieces.append(e["data"])

        # Only the first token ("TARS: ") was yielded before client disconnection was detected
        assert token_pieces == ["TARS: "]

        # Stream ended prematurely before reaching stream_end or done
        event_names = [e.get("event") for e in events if "event" in e]
        assert "stream_end" not in event_names
        assert "done" not in event_names

        # Verify disconnection log entry
        assert any(
            "Client disconnected from SSE stream" in str(arg)
            for call in mock_log_info.call_args_list
            for arg in call.args
        )

