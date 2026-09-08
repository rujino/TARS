"""Tier 1 Unit Tests: Google Workspace Adapters (Calendar & Gmail) and Auth.

Tests:
1. GoogleAuthHelper mock mode resolution, token retrieval, and authorization header construction.
2. GoogleCalendarAdapter event listing, creation, updating, deletion, freebusy query, and datetime/Meet handling.
3. GmailAdapter email search, detail retrieval, thread/ownership analysis, drafting, and message sending in mock mode.
4. Tool input coercion and defensive parsing (StringList, DictList, JsonDict).
"""

from __future__ import annotations

import pytest

from tars.tools.base import (
    coerce_json_str_to_dict,
    coerce_json_str_to_list,
)
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import (
    CalendarCreateEventTool,
    CalendarDeleteEventTool,
    CalendarListEventsTool,
    CalendarQueryFreeBusyTool,
    CalendarUpdateEventTool,
    GoogleCalendarAdapter,
)
from tars.tools.google.datetime_utils import (
    build_time_boundary,
    normalize_calendar_time,
    resolve_conference_data,
    strip_utc_offset,
)
from tars.tools.google.gmail import (
    GmailAdapter,
    GmailDraftMessageTool,
    GmailGetThreadTool,
    GmailSearchMessagesTool,
    GmailSendMessageTool,
    html_to_plain_text,
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
# 2. Defensive Coercion & Datetime Utilities Tests
# ============================================================================


def test_coercion_helpers() -> None:
    """Verify JSON string coercion into native Python containers."""
    # List coercion
    assert coerce_json_str_to_list('["alice@test.com", "bob@test.com"]') == [
        "alice@test.com",
        "bob@test.com",
    ]
    assert coerce_json_str_to_list(["already", "list"]) == ["already", "list"]
    assert coerce_json_str_to_list("invalid json") == "invalid json"

    # Dict coercion
    assert coerce_json_str_to_dict('{"key": "value"}') == {"key": "value"}
    assert coerce_json_str_to_dict({"already": "dict"}) == {"already": "dict"}


def test_datetime_and_timezone_utilities() -> None:
    """Verify calendar boundary building, offset stripping, and Meet configuration."""
    # Offset stripping
    assert strip_utc_offset("2026-03-19T12:00:00-08:00") == "2026-03-19T12:00:00"
    assert strip_utc_offset("2026-03-19T12:00:00Z") == "2026-03-19T12:00:00"

    # Normalization
    assert normalize_calendar_time(' "2026-09-08T10:00:00Z" ') == "2026-09-08T10:00:00Z"
    assert normalize_calendar_time("null") is None

    # All-day boundary vs Timed boundary
    all_day = build_time_boundary("2026-09-08")
    assert all_day == {"date": "2026-09-08"}

    timed_utc = build_time_boundary("2026-09-08T10:00:00Z")
    assert timed_utc == {"dateTime": "2026-09-08T10:00:00Z"}

    timed_tz = build_time_boundary("2026-09-08T19:00:00+09:00", "Asia/Seoul")
    assert timed_tz == {"dateTime": "2026-09-08T19:00:00", "timeZone": "Asia/Seoul"}

    # Google Meet configuration
    conf_data, params = resolve_conference_data(add_google_meet=True)
    assert conf_data is not None
    assert params["conferenceDataVersion"] == 1


# ============================================================================
# 3. Google Calendar Adapter & Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_google_calendar_adapter_lifecycle() -> None:
    """Verify Calendar list, create, update, freebusy, and delete operations in mock mode."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    calendar_adapter = GoogleCalendarAdapter(auth_helper=auth_helper)

    # 1. List initial mock events (compact view)
    events = await calendar_adapter.list_events()
    assert len(events) >= 2
    summaries = [e["summary"] for e in events]
    assert "Endurance Mission Briefing" in summaries

    # 2. Create a new event with Google Meet & Timezone
    new_event = await calendar_adapter.create_event(
        summary="Gargantua Slingshot Maneuver",
        start_time="2026-09-02T08:00:00",
        end_time="2026-09-02T12:00:00",
        timezone="Asia/Seoul",
        description="Manual navigation burn at 100% engine thrust.",
        attendees=["cooper@endurance.space", "tars@endurance.space"],
        add_google_meet=True,
    )
    assert new_event["id"].startswith("evt_")
    assert new_event["summary"] == "Gargantua Slingshot Maneuver"
    assert new_event["status"] == "confirmed"
    assert "meet.google.com" in new_event.get("hangoutLink", "")
    assert new_event["start"]["timeZone"] == "Asia/Seoul"

    # 3. Update the event while preserving description & attendees
    updated = await calendar_adapter.update_event(
        event_id=new_event["id"],
        summary="Gargantua Slingshot Maneuver - Revised",
        start_time="2026-09-02T09:00:00",
        end_time="2026-09-02T13:00:00",
        timezone="Asia/Seoul",
    )
    assert updated["summary"] == "Gargantua Slingshot Maneuver - Revised"
    assert updated["description"] == "Manual navigation burn at 100% engine thrust."
    assert len(updated["attendees"]) == 2

    # 4. Query FreeBusy
    fb = await calendar_adapter.query_freebusy(
        time_min="2026-09-02T00:00:00Z",
        time_max="2026-09-02T23:59:59Z",
    )
    assert fb["kind"] == "calendar#freeBusy"
    cal_id = list(fb["calendars"].keys())[0]
    assert len(fb["calendars"][cal_id]["busy"]) >= 1

    # 5. Delete the event
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
    assert len(tools) == 5

    registry = ToolRegistry(tools)
    assert registry.has_tool("calendar_list_events")
    assert registry.has_tool("calendar_create_event")
    assert registry.has_tool("calendar_update_event")
    assert registry.has_tool("calendar_delete_event")
    assert registry.has_tool("calendar_query_freebusy")

    # Execute list tool with detailed=False
    list_tool = registry.get_tool("calendar_list_events")
    assert isinstance(list_tool, CalendarListEventsTool)
    res_list = await registry.execute_tool("calendar_list_events", {"max_results": 1, "detailed": False})
    assert len(res_list) == 1

    # Execute create tool with all-day boundary
    create_tool = registry.get_tool("calendar_create_event")
    assert isinstance(create_tool, CalendarCreateEventTool)
    created = await registry.execute_tool(
        "calendar_create_event",
        {
            "summary": "Planetary Descent",
            "start_time": "2026-09-05",
            "end_time": "2026-09-06",
            "add_google_meet": True,
        },
    )
    assert created["summary"] == "Planetary Descent"
    assert created["start"] == {"date": "2026-09-05"}
    assert "meet.google.com" in created["hangoutLink"]

    # Execute update tool
    update_tool = registry.get_tool("calendar_update_event")
    assert isinstance(update_tool, CalendarUpdateEventTool)
    updated = await registry.execute_tool(
        "calendar_update_event",
        {"event_id": created["id"], "summary": "Planetary Descent Finalized"},
    )
    assert updated["summary"] == "Planetary Descent Finalized"

    # Execute freebusy tool
    fb_tool = registry.get_tool("calendar_query_freebusy")
    assert isinstance(fb_tool, CalendarQueryFreeBusyTool)
    fb_res = await registry.execute_tool(
        "calendar_query_freebusy",
        {"time_min": "2026-09-01T00:00:00Z", "time_max": "2026-09-08T00:00:00Z"},
    )
    assert "calendars" in fb_res

    # Execute delete tool
    delete_tool = registry.get_tool("calendar_delete_event")
    assert isinstance(delete_tool, CalendarDeleteEventTool)
    deleted = await registry.execute_tool("calendar_delete_event", {"event_id": created["id"]})
    assert deleted["status"] == "deleted"


# ============================================================================
# 4. Gmail Adapter & Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_gmail_adapter_lifecycle() -> None:
    """Verify Gmail search, get, thread ownership, drafting, and send operations."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    gmail_adapter = GmailAdapter(auth_helper=auth_helper)

    # 1. Search messages by query filter
    unread_msgs = await gmail_adapter.search_messages("is:unread")
    assert len(unread_msgs) >= 1
    assert unread_msgs[0]["id"] == "msg_001"
    assert "web_link" in unread_msgs[0]

    # 2. Get message detail
    detail = await gmail_adapter.get_message("msg_001")
    assert detail["from"] == "cooper@endurance.space"
    assert "Gargantua" in detail["body"]

    # Nonexistent message raises KeyError
    with pytest.raises(KeyError):
        await gmail_adapter.get_message("msg_nonexistent_999")

    # 3. Get thread with ball-in-court analysis
    thread_res = await gmail_adapter.get_thread("th_001", include_analysis=True)
    assert thread_res["thread_id"] == "th_001"
    assert thread_res["message_count"] >= 1
    assert thread_res["analysis"]["last_sender"] == "cooper@endurance.space"
    assert thread_res["analysis"]["ball_in_court_of"] == "action_required"

    # 4. Draft email message
    draft_res = await gmail_adapter.draft_message(
        to="brand@endurance.space",
        subject="Draft: Orbital Path Review",
        body="Draft proposal for slingshot trajectory.",
        thread_id="th_001",
    )
    assert draft_res["status"] == "draft_created"
    assert draft_res["threadId"] == "th_001"

    # 5. Send email message with quote_original
    sent_result = await gmail_adapter.send_message(
        to="cooper@endurance.space",
        subject="Re: Trajectory Calculation Request",
        body="Trajectory calculations verified. 100% confidence.",
        thread_id="th_001",
        quote_original=True,
    )
    assert sent_result["status"] == "sent"
    assert sent_result["threadId"] == "th_001"

    # Verify sent message is in mock store and includes quoted original
    retrieved = await gmail_adapter.get_message(sent_result["id"])
    assert "Trajectory calculations verified." in retrieved["body"]
    assert "On 2026-08-25T08:30:00Z, cooper@endurance.space wrote:" in retrieved["body"]


@pytest.mark.asyncio
async def test_gmail_tools_execution() -> None:
    """Verify executing BaseTool wrappers for Gmail."""
    gmail_adapter = GmailAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    tools = gmail_adapter.get_tools()
    assert len(tools) == 5

    registry = ToolRegistry(tools)
    assert registry.has_tool("gmail_search_messages")
    assert registry.has_tool("gmail_get_message")
    assert registry.has_tool("gmail_get_thread")
    assert registry.has_tool("gmail_send_message")
    assert registry.has_tool("gmail_draft_message")

    # Execute search tool
    search_tool = registry.get_tool("gmail_search_messages")
    assert isinstance(search_tool, GmailSearchMessagesTool)
    search_res = await registry.execute_tool("gmail_search_messages", {"query": "Plan B"})
    assert len(search_res) >= 1
    assert "Plan B" in search_res[0]["subject"]

    # Execute get thread tool
    thread_tool = registry.get_tool("gmail_get_thread")
    assert isinstance(thread_tool, GmailGetThreadTool)
    th_res = await registry.execute_tool("gmail_get_thread", {"thread_id": "th_002"})
    assert th_res["message_count"] >= 1

    # Execute draft tool
    draft_tool = registry.get_tool("gmail_draft_message")
    assert isinstance(draft_tool, GmailDraftMessageTool)
    draft_res = await registry.execute_tool(
        "gmail_draft_message",
        {
            "to": "murph@nasa.gov",
            "subject": "Black Hole Telemetry Draft",
            "body": "Do not go gentle into that good night.",
        },
    )
    assert draft_res["status"] == "draft_created"

    # Execute send tool
    send_tool = registry.get_tool("gmail_send_message")
    assert isinstance(send_tool, GmailSendMessageTool)
    send_res = await registry.execute_tool(
        "gmail_send_message",
        {
            "to": "murph@nasa.gov",
            "subject": "Quantum Data Transmission",
            "body": "It's all here, Murph. Stay.",
            "body_format": "plain",
        },
    )
    assert send_res["status"] == "sent"


def test_html_to_plain_text() -> None:
    """Verify HTML extractor cleans tags and preserves linebreaks."""
    sample_html = "<h3>Meeting Agenda</h3><p>Review trajectory.</p><p>Check telemetry.</p>"
    plain = html_to_plain_text(sample_html)
    assert "Meeting Agenda" in plain
    assert "Review trajectory." in plain
    assert "Check telemetry." in plain
    assert "<p>" not in plain
