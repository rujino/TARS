"""Tier 1 Unit Tests: Temporal Grounding and Calendar Default Range.

Tests:
1. get_current_temporal_context: JIT resolution across timezones and fallback handling.
2. prompt_node: dynamic injection of [CURRENT TEMPORAL CONTEXT] into system prompt.
3. CalendarListEventsTool: schema temporal guidance and API params timeMin fallback.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from tars.core.temporal import get_current_temporal_context
from tars.orchestrator.nodes import prompt_node
from tars.orchestrator.state import TARSState
from tars.persona.prompts import build_tars_system_prompt
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import CalendarListEventsTool, GoogleCalendarAdapter


def test_get_current_temporal_context_resolution() -> None:
    """Verify temporal context calculation with fixed reference time and timezones."""
    fixed_ref = datetime.datetime(2026, 9, 8, 17, 30, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    ctx_kst = get_current_temporal_context("Asia/Seoul", reference_time=fixed_ref)

    assert ctx_kst["date_str"] == "2026-09-08"
    assert ctx_kst["time_str"] == "17:30:00"
    assert ctx_kst["day_of_week"] == "Tuesday"
    assert ctx_kst["timezone"] == "Asia/Seoul"
    assert "[CURRENT TEMPORAL CONTEXT]" in ctx_kst["prompt_section"]
    assert "2026-09-08 17:30:00 (Asia/Seoul)" in ctx_kst["prompt_section"]

    # America/New_York (-13 hours from KST in September EDT)
    ctx_ny = get_current_temporal_context("America/New_York", reference_time=fixed_ref)
    assert ctx_ny["date_str"] == "2026-09-08"
    assert ctx_ny["time_str"] == "04:30:00"
    assert ctx_ny["timezone"] == "America/New_York"

    # Invalid timezone fallback to Asia/Seoul
    ctx_invalid = get_current_temporal_context("Invalid/TimeZone_DoesNotExist", reference_time=fixed_ref)
    assert ctx_invalid["timezone"] == "Asia/Seoul"
    assert ctx_invalid["date_str"] == "2026-09-08"


def test_build_tars_system_prompt_includes_temporal_context() -> None:
    """Verify build_tars_system_prompt injects [CURRENT TEMPORAL CONTEXT] seamlessly."""
    fixed_ref = datetime.datetime(2026, 9, 8, 10, 15, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    prompt = build_tars_system_prompt(
        humor_level=0.9,
        honesty_level=0.95,
        mode="companion",
        client_timezone="Asia/Seoul",
        reference_time=fixed_ref,
    )

    assert "[CURRENT TEMPORAL CONTEXT]" in prompt
    assert "- Current Local Time: 2026-09-08 10:15:00 (Asia/Seoul)" in prompt
    assert "- Current Day of the Week: Tuesday" in prompt
    assert "[SYSTEM DIRECTIVE PRIORITY]" in prompt


@pytest.mark.asyncio
async def test_prompt_node_dynamic_temporal_injection() -> None:
    """Verify prompt_node dynamically resolves temporal context on each invocation."""
    fixed_ref = datetime.datetime(2026, 9, 9, 14, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    state: TARSState = {
        "user_id": "test_user_001",
        "client_timezone": "Asia/Seoul",
        "reference_time": fixed_ref,
        "humor_level": 0.9,
        "honesty_level": 0.95,
        "mode": "companion",
        "relevant_wikis": [],
    }

    result = await prompt_node(state)
    system_prompt = result["system_prompt"]

    assert "[CURRENT TEMPORAL CONTEXT]" in system_prompt
    assert "2026-09-09 14:00:00 (Asia/Seoul)" in system_prompt
    assert "Wednesday" in system_prompt


def test_calendar_tool_schema_temporal_guidance() -> None:
    """Verify CalendarListEventsTool schema explains ascending sort order and now default."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    adapter = GoogleCalendarAdapter(auth_helper=auth_helper)
    tool = CalendarListEventsTool(adapter)

    decl = tool.to_gemini_declaration()
    assert "chronological ascending order" in decl["description"]

    prop_time_min = decl["parameters"]["properties"]["time_min"]
    assert "Defaults to current time if omitted" in prop_time_min["description"]
