"""Google Calendar API Adapter and Tools for TARS.

Supports:
- calendar_list_events: Query upcoming events
- calendar_create_event: Schedule new event
- calendar_delete_event: Delete an event by ID
- Deterministic in-memory mock mode for offline testing
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from tars.config import get_settings
from tars.tools.base import BaseTool
from tars.tools.google.auth import GoogleAuthHelper

logger = logging.getLogger("tars.tools.google.calendar")


class GoogleCalendarAdapter:
    """Manager and client adapter for Google Calendar operations."""

    def __init__(
        self,
        auth_helper: GoogleAuthHelper | None = None,
        calendar_id: str | None = None,
    ) -> None:
        self.auth_helper = auth_helper or GoogleAuthHelper()
        self.calendar_id = calendar_id or get_settings().google_calendar_id
        # In-memory store for deterministic mock testing
        self._mock_events: dict[str, dict[str, Any]] = {
            "evt_001": {
                "id": "evt_001",
                "summary": "Endurance Mission Briefing",
                "start": {"dateTime": "2026-08-30T10:00:00Z"},
                "end": {"dateTime": "2026-08-30T11:30:00Z"},
                "description": "Pre-flight trajectory and wormhole traversal review.",
                "attendees": [
                    {"email": "cooper@endurance.space"},
                    {"email": "brand@endurance.space"},
                ],
                "status": "confirmed",
            },
            "evt_002": {
                "id": "evt_002",
                "summary": "TARS Humor Calibration",
                "start": {"dateTime": "2026-08-31T14:00:00Z"},
                "end": {"dateTime": "2026-08-31T15:00:00Z"},
                "description": "Adjusting sarcasm parameters down to 90%.",
                "attendees": [{"email": "cooper@endurance.space"}],
                "status": "confirmed",
            },
        }

    async def list_events(
        self,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """List events in calendar."""
        if self.auth_helper.mock_mode:
            events = list(self._mock_events.values())
            if time_min:
                events = [e for e in events if e.get("start", {}).get("dateTime", "") >= time_min]
            if time_max:
                events = [e for e in events if e.get("end", {}).get("dateTime", "") <= time_max]
            return events[:max_results]

        headers = await self.auth_helper.get_auth_headers()
        url = f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
        params: dict[str, str | int | bool] = {
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max

        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        items: list[dict[str, Any]] = data.get("items", [])
        return items

    async def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        attendees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new event in calendar."""
        attendee_list = [{"email": email} for email in (attendees or [])]
        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
            "attendees": attendee_list,
        }

        if self.auth_helper.mock_mode:
            event_id = f"evt_{uuid.uuid4().hex[:8]}"
            created_event = {
                "id": event_id,
                **event_body,
                "status": "confirmed",
            }
            self._mock_events[event_id] = created_event
            logger.info("Mock created calendar event: %s (%s)", event_id, summary)
            return created_event

        headers = await self.auth_helper.get_auth_headers()
        url = f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, json=event_body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def delete_event(self, event_id: str) -> dict[str, Any]:
        """Delete an event from calendar."""
        if self.auth_helper.mock_mode:
            if event_id in self._mock_events:
                del self._mock_events[event_id]
                return {"status": "deleted", "event_id": event_id}
            raise KeyError(f"Event ID '{event_id}' not found.")

        headers = await self.auth_helper.get_auth_headers()
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{event_id}"
        )
        client = self.auth_helper._get_http_client()
        resp = await client.delete(url, headers=headers)
        resp.raise_for_status()
        return {"status": "deleted", "event_id": event_id}

    def get_tools(self) -> list[BaseTool]:
        """Return BaseTool wrapper instances for all calendar actions."""
        return [
            CalendarListEventsTool(adapter=self),
            CalendarCreateEventTool(adapter=self),
            CalendarDeleteEventTool(adapter=self),
        ]


class CalendarListEventsTool(BaseTool):
    """Tool to list events from Google Calendar."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_list_events",
            description="List scheduled events from Google Calendar within an optional time window.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Lower bound RFC3339 timestamp (e.g. '2026-08-30T00:00:00Z')",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "Upper bound RFC3339 timestamp (e.g. '2026-08-31T23:59:59Z')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to retrieve (default: 10)",
                        "default": 10,
                    },
                },
                "required": [],
            },
        )

    async def aexecute(self, **kwargs: Any) -> list[dict[str, Any]]:
        time_min = kwargs.get("time_min")
        time_max = kwargs.get("time_max")
        max_results = int(kwargs.get("max_results", 10))
        return await self.adapter.list_events(
            time_min=time_min, time_max=time_max, max_results=max_results
        )


class CalendarCreateEventTool(BaseTool):
    """Tool to create a new event in Google Calendar."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_create_event",
            description="Create a new event in Google Calendar with summary, start time, end time, and attendees.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title or summary of the event",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start timestamp in RFC3339/ISO8601 format (e.g. '2026-09-01T15:00:00Z')",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End timestamp in RFC3339/ISO8601 format (e.g. '2026-09-01T16:00:00Z')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description or meeting agenda",
                        "default": "",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of attendee email addresses",
                        "default": [],
                    },
                },
                "required": ["summary", "start_time", "end_time"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        summary = str(kwargs.get("summary", ""))
        start_time = str(kwargs.get("start_time", ""))
        end_time = str(kwargs.get("end_time", ""))
        description = str(kwargs.get("description", ""))
        attendees = kwargs.get("attendees")
        return await self.adapter.create_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            attendees=attendees,
        )


class CalendarDeleteEventTool(BaseTool):
    """Tool to delete an event from Google Calendar."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_delete_event",
            description="Delete an existing event from Google Calendar by its unique event ID.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The unique event identifier to delete",
                    },
                },
                "required": ["event_id"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        event_id = str(kwargs.get("event_id", ""))
        return await self.adapter.delete_event(event_id=event_id)


__all__ = [
    "CalendarCreateEventTool",
    "CalendarDeleteEventTool",
    "CalendarListEventsTool",
    "GoogleCalendarAdapter",
]
