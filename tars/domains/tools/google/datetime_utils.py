"""Datetime and timezone utilities for Google Calendar API integrations.

Provides defensive parsing, timezone normalization, and payload boundary builders
to bridge LLM-generated date/time inputs with Google Calendar API specifications.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("tars.tools.google.datetime_utils")


def strip_utc_offset(datetime_str: str) -> str:
    """Strip UTC offset from an RFC3339/ISO8601 dateTime string, returning naive local time.

    When an IANA timezone (e.g. America/Los_Angeles, Asia/Seoul) is provided alongside
    a dateTime, the Google Calendar API uses the explicit offset for scheduling and
    only uses the IANA timezone for recurrence expansion. If an LLM generates a static
    or inaccurate offset (e.g. -08:00 during Daylight Saving Time), wall-clock time is corrupted.

    By stripping the offset and passing naive local time + IANA timeZone,
    Google Calendar resolves the correct DST-aware offset automatically.

    Examples:
        "2026-03-19T12:00:00-08:00" -> "2026-03-19T12:00:00"
        "2026-03-19T12:00:00Z"      -> "2026-03-19T12:00:00"
        "2026-03-19T12:00:00"       -> "2026-03-19T12:00:00"
    """
    if datetime_str.endswith("Z") or datetime_str.endswith("z"):
        return datetime_str[:-1]
    return re.sub(r"[+-]\d{2}:\d{2}$", "", datetime_str)


def normalize_calendar_time(time_str: str | None) -> str | None:
    """Defensively clean and normalize raw LLM date/time strings."""
    if not time_str:
        return None

    # Strip accidental surrounding quotes, single quotes, and whitespace
    cleaned = time_str.strip().strip("\"'").strip()
    if not cleaned or cleaned.lower() in ("null", "none"):
        return None

    return cleaned


def build_time_boundary(time_value: str, timezone: str | None = None) -> dict[str, str]:
    """Build a Google Calendar start or end boundary object.

    Handles the fundamental Google Calendar API distinction:
    - All-day events: {"date": "YYYY-MM-DD"}
    - Timed events: {"dateTime": "...", "timeZone": "..."}

    Args:
        time_value: Date string ("YYYY-MM-DD") or datetime string ("YYYY-MM-DDTHH:MM:SS").
        timezone: Optional IANA timezone identifier (e.g. "Asia/Seoul").

    Returns:
        Dictionary formatted for Google Calendar API v3 resource payload.

    Raises:
        ValueError: If time_value is empty or timezone is unrecognized.
    """
    cleaned = normalize_calendar_time(time_value)
    if not cleaned:
        raise ValueError("time_value cannot be empty.")

    # All-day format: YYYY-MM-DD (no time component)
    if "T" not in cleaned:
        return {"date": cleaned}

    # Timed event without specified timezone: return dateTime as-is
    if not timezone:
        return {"dateTime": cleaned}

    # Validate timezone identifier
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unrecognized IANA timezone {timezone!r}. Use a valid identifier such as 'Asia/Seoul' or 'America/New_York'."
        ) from exc

    # With IANA timezone provided, strip offset to let Google Calendar handle DST correctly
    naive_time = strip_utc_offset(cleaned)
    return {"dateTime": naive_time, "timeZone": timezone}


def resolve_conference_data(
    add_google_meet: bool = False,
    request_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build Google Meet conferenceData and associated query parameters.

    Important: Google Calendar API requires '?conferenceDataVersion=1' query parameter
    on insert/patch requests; otherwise conferenceData is silently ignored.
    """
    if not add_google_meet:
        return None, {}

    import uuid

    req_id = request_id or f"meet_{uuid.uuid4().hex[:12]}"
    conference_data = {
        "createRequest": {
            "requestId": req_id,
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }
    params = {"conferenceDataVersion": 1}
    return conference_data, params
