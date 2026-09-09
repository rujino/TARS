"""Temporal context utilities for TARS agents and tools."""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_current_temporal_context(
    client_timezone: str = "Asia/Seoul",
    reference_time: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Calculate real-time JIT temporal context for prompt injection and tools.

    Args:
        client_timezone: IANA timezone identifier (e.g. 'Asia/Seoul', 'America/New_York').
        reference_time: Optional fixed reference time (primarily for deterministic unit testing).

    Returns:
        dict containing now_utc, local_now, ISO strings, day of week, and formatted prompt text.
    """
    try:
        tz = ZoneInfo(client_timezone)
    except (ZoneInfoNotFoundError, ValueError, Exception):
        tz = ZoneInfo("Asia/Seoul")

    now_utc = (
        reference_time.astimezone(datetime.timezone.utc)
        if reference_time
        else datetime.datetime.now(datetime.timezone.utc)
    )
    local_now = now_utc.astimezone(tz)

    day_of_week = local_now.strftime("%A")
    date_str = local_now.strftime("%Y-%m-%d")
    time_str = local_now.strftime("%H:%M:%S")
    tz_name = (
        client_timezone
        if getattr(tz, "key", "") == client_timezone
        else getattr(tz, "key", client_timezone)
    )

    prompt_section = (
        "[CURRENT TEMPORAL CONTEXT]\n"
        f"- Current Local Time: {date_str} {time_str} ({tz_name})\n"
        f"- Current Day of the Week: {day_of_week}\n"
        f"- Current UTC Time: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        "- Operational Directive: Use this temporal context as the absolute ground truth reference for any "
        "relative time calculations (e.g. 'today', 'tomorrow', 'yesterday', 'latest events', 'next week')."
    )

    return {
        "now_utc": now_utc,
        "local_now": local_now,
        "date_str": date_str,
        "time_str": time_str,
        "day_of_week": day_of_week,
        "timezone": tz_name,
        "prompt_section": prompt_section,
    }


__all__ = ["get_current_temporal_context"]
