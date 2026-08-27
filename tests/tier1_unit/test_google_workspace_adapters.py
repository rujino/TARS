"""Tier 1 Unit Tests: Google Workspace Adapters (Calendar & Gmail) and Auth.

Tests:
1. GoogleAuthHelper mock mode resolution, token retrieval, and authorization header construction.
2. GoogleCalendarAdapter event listing, creation, and deletion via tools in mock mode.
3. GmailAdapter email search, detail retrieval, and message sending via tools in mock mode.
"""

from __future__ import annotations

import pytest

from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import (
    CalendarCreateEventTool,
    CalendarDeleteEventTool,
    CalendarListEventsTool,
    GoogleCalendarAdapter,
)
from tars.tools.google.gmail import (
    GmailAdapter,
    GmailGetMessageTool,
    GmailSearchMessagesTool,
    GmailSendMessageTool,
)
from tars.tools.registry import ToolRegistry

# ============================================================================
# 1. GoogleAuthHelper Tests
# ============================================================================


@pytest.mark.asyncio
async def test_google_auth_helper_mock_mode_behavior() -> None:
    """Verify GoogleAuthHelper defaults to mock mode and returns mock access tokens."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    assert auth_helper.mock_mode is True

    token = await auth_helper.get_access_token()
    assert "mock" in token

    headers = await auth_helper.get_auth_headers()
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["Content-Type"] == "application/json"

    await auth_helper.close()


# ============================================================================
# 2. Google Calendar Adapter & Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_google_calendar_adapter_lifecycle() -> None:
    """Verify Calendar list, create, and delete operations in mock mode."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    calendar_adapter = GoogleCalendarAdapter(auth_helper=auth_helper)

    # 1. List initial mock events
    events = await calendar_adapter.list_events()
    assert len(events) >= 2
    summaries = [e["summary"] for e in events]
    assert "Endurance Mission Briefing" in summaries

    # 2. Create a new event
    new_event = await calendar_adapter.create_event(
        summary="Gargantua Slingshot Maneuver",
        start_time="2026-09-02T08:00:00Z",
        end_time="2026-09-02T12:00:00Z",
        description="Manual navigation burn at 100% engine thrust.",
        attendees=["cooper@endurance.space", "tars@endurance.space"],
    )
    assert new_event["id"].startswith("evt_")
    assert new_event["summary"] == "Gargantua Slingshot Maneuver"
    assert new_event["status"] == "confirmed"

    # Verify event is in list
    updated_events = await calendar_adapter.list_events()
    assert any(e["id"] == new_event["id"] for e in updated_events)

    # 3. Delete the event
    del_result = await calendar_adapter.delete_event(new_event["id"])
    assert del_result["status"] == "deleted"
    assert del_result["event_id"] == new_event["id"]

    # Deleting again raises KeyError
    with pytest.raises(KeyError):
        await calendar_adapter.delete_event(new_event["id"])


@pytest.mark.asyncio
async def test_google_calendar_tools_execution() -> None:
    """Verify executing BaseTool wrappers for Google Calendar."""
    calendar_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    tools = calendar_adapter.get_tools()
    assert len(tools) == 3

    registry = ToolRegistry(tools)
    assert registry.has_tool("calendar_list_events")
    assert registry.has_tool("calendar_create_event")
    assert registry.has_tool("calendar_delete_event")

    # Execute list tool
    list_tool = registry.get_tool("calendar_list_events")
    assert isinstance(list_tool, CalendarListEventsTool)
    res_list = await registry.execute_tool("calendar_list_events", {"max_results": 1})
    assert len(res_list) == 1

    # Execute create tool
    create_tool = registry.get_tool("calendar_create_event")
    assert isinstance(create_tool, CalendarCreateEventTool)
    created = await registry.execute_tool(
        "calendar_create_event",
        {
            "summary": "Planetary Descent",
            "start_time": "2026-09-05T00:00:00Z",
            "end_time": "2026-09-05T04:00:00Z",
        },
    )
    assert created["summary"] == "Planetary Descent"

    # Execute delete tool
    delete_tool = registry.get_tool("calendar_delete_event")
    assert isinstance(delete_tool, CalendarDeleteEventTool)
    deleted = await registry.execute_tool("calendar_delete_event", {"event_id": created["id"]})
    assert deleted["status"] == "deleted"


# ============================================================================
# 3. Gmail Adapter & Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_gmail_adapter_lifecycle() -> None:
    """Verify Gmail search, get, and send operations in mock mode."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    gmail_adapter = GmailAdapter(auth_helper=auth_helper)

    # 1. Search messages by query filter
    unread_msgs = await gmail_adapter.search_messages("is:unread")
    assert len(unread_msgs) >= 1
    assert unread_msgs[0]["id"] == "msg_001"

    from_cooper = await gmail_adapter.search_messages("from:cooper")
    assert len(from_cooper) >= 1
    assert "Trajectory" in from_cooper[0]["subject"]

    # 2. Get message detail
    detail = await gmail_adapter.get_message("msg_001")
    assert detail["from"] == "cooper@endurance.space"
    assert "Gargantua" in detail["body"]

    # Nonexistent message raises KeyError
    with pytest.raises(KeyError):
        await gmail_adapter.get_message("msg_nonexistent_999")

    # 3. Send email message
    sent_result = await gmail_adapter.send_message(
        to="brand@endurance.space",
        subject="Orbital Trajectory Confirmed",
        body="Cooper and I calculated the slingshot angle. Sarcasm remains at 90%.",
    )
    assert sent_result["status"] == "sent"
    assert sent_result["to"] == "brand@endurance.space"

    # Verify sent message is retrievable
    retrieved = await gmail_adapter.get_message(sent_result["id"])
    assert retrieved["subject"] == "Orbital Trajectory Confirmed"
    assert "Cooper and I" in retrieved["body"]


@pytest.mark.asyncio
async def test_gmail_tools_execution() -> None:
    """Verify executing BaseTool wrappers for Gmail."""
    gmail_adapter = GmailAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    tools = gmail_adapter.get_tools()
    assert len(tools) == 3

    registry = ToolRegistry(tools)
    assert registry.has_tool("gmail_search_messages")
    assert registry.has_tool("gmail_get_message")
    assert registry.has_tool("gmail_send_message")

    # Execute search tool
    search_tool = registry.get_tool("gmail_search_messages")
    assert isinstance(search_tool, GmailSearchMessagesTool)
    search_res = await registry.execute_tool("gmail_search_messages", {"query": "Plan B"})
    assert len(search_res) >= 1
    assert "Plan B" in search_res[0]["subject"]

    # Execute get tool
    get_tool = registry.get_tool("gmail_get_message")
    assert isinstance(get_tool, GmailGetMessageTool)
    get_res = await registry.execute_tool("gmail_get_message", {"message_id": search_res[0]["id"]})
    assert "Edmunds" in get_res["body"]

    # Execute send tool
    send_tool = registry.get_tool("gmail_send_message")
    assert isinstance(send_tool, GmailSendMessageTool)
    send_res = await registry.execute_tool(
        "gmail_send_message",
        {
            "to": "murph@nasa.gov",
            "subject": "Quantum Data Transmission",
            "body": "It's all here, Murph. Stay.",
        },
    )
    assert send_res["status"] == "sent"
