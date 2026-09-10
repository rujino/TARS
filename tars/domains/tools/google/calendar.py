"""Google Calendar API Adapter and Tools for TARS.

Supports:
- calendar_list_events: Query upcoming events with keyword search & concise/detailed modes
- calendar_create_event: Schedule new event with timezone & Google Meet support
- calendar_update_event: Update an existing event while preserving untouched fields
- calendar_delete_event: Delete an event by ID
- calendar_query_freebusy: Check schedule availability and busy intervals across calendars
- Deterministic in-memory mock mode for offline testing
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from tars.config import get_settings
from tars.domains.tools.base import BaseTool, coerce_to_string_list
from tars.domains.tools.google.auth import GoogleAuthHelper
from tars.domains.tools.google.datetime_utils import (
    build_time_boundary,
    normalize_calendar_time,
    resolve_conference_data,
)

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
                "hangoutLink": "https://meet.google.com/end-uran-ce1",
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

    async def close(self) -> None:
        """Close underlying authentication and HTTP resources."""
        if hasattr(self.auth_helper, "close"):
            await self.auth_helper.close()

    async def aclose(self) -> None:
        """Async close alias."""
        await self.close()

    async def list_events(
        self,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        query: str | None = None,
        detailed: bool = False,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List events in calendar with optional filtering, search query, and detail level."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        norm_time_min = normalize_calendar_time(time_min)
        norm_time_max = normalize_calendar_time(time_max)

        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            events = list(self._mock_events.values())
            if norm_time_min:
                events = [
                    e
                    for e in events
                    if (e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", ""))
                    >= norm_time_min
                ]
            if norm_time_max:
                events = [
                    e
                    for e in events
                    if (e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", ""))
                    <= norm_time_max
                ]
            if query:
                q_lower = query.lower()
                events = [
                    e
                    for e in events
                    if q_lower in e.get("summary", "").lower()
                    or q_lower in e.get("description", "").lower()
                ]

            events = events[:max_results]
            if not detailed:
                return [
                    {
                        "id": e.get("id"),
                        "summary": e.get("summary"),
                        "start": e.get("start"),
                        "end": e.get("end"),
                        "status": e.get("status"),
                        "hangoutLink": e.get("hangoutLink"),
                    }
                    for e in events
                ]
            return events

        url = f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
        params: dict[str, str | int | bool] = {
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if norm_time_min:
            params["timeMin"] = norm_time_min
        elif not norm_time_max and not query:
            import datetime

            params["timeMin"] = (
                datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            )
        if norm_time_max:
            params["timeMax"] = norm_time_max
        if query:
            params["q"] = query

        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        items: list[dict[str, Any]] = data.get("items", [])

        if not detailed:
            return [
                {
                    "id": e.get("id"),
                    "summary": e.get("summary"),
                    "start": e.get("start"),
                    "end": e.get("end"),
                    "status": e.get("status"),
                    "hangoutLink": e.get("hangoutLink"),
                }
                for e in items
            ]
        return items

    async def get_event(self, event_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Retrieve full details of a specific event by ID."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            if event_id in self._mock_events:
                return self._mock_events[event_id]
            raise KeyError(f"Event ID '{event_id}' not found.")

        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{event_id}"
        )
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        attendees: list[str] | None = None,
        timezone: str | None = None,
        add_google_meet: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new event in calendar with timezone, all-day, and Google Meet support."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        attendee_list = [{"email": email} for email in coerce_to_string_list(attendees)]

        start_boundary = build_time_boundary(start_time, timezone)
        end_boundary = build_time_boundary(end_time, timezone)
        conf_data, conf_params = resolve_conference_data(add_google_meet=add_google_meet)

        event_body: dict[str, Any] = {
            "summary": summary,
            "description": description,
            "start": start_boundary,
            "end": end_boundary,
            "attendees": attendee_list,
        }
        if conf_data:
            event_body["conferenceData"] = conf_data

        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            event_id = f"evt_{uuid.uuid4().hex[:8]}"
            created_event = {
                "id": event_id,
                **event_body,
                "status": "confirmed",
            }
            if add_google_meet:
                created_event["hangoutLink"] = (
                    f"https://meet.google.com/{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:3]}"
                )
            self._mock_events[event_id] = created_event
            logger.info("Mock created calendar event: %s (%s)", event_id, summary)
            return created_event

        url = f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, params=conf_params, json=event_body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def update_event(
        self,
        event_id: str,
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
        timezone: str | None = None,
        add_google_meet: bool | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing event, preserving untouched fields."""
        existing = await self.get_event(event_id=event_id, user_id=user_id)
        patch_body: dict[str, Any] = {}

        if summary is not None:
            patch_body["summary"] = summary
        if description is not None:
            patch_body["description"] = description

        # Boundaries
        if start_time is not None:
            patch_body["start"] = build_time_boundary(start_time, timezone)
        if end_time is not None:
            patch_body["end"] = build_time_boundary(end_time, timezone)

        # Attendees
        if attendees is not None:
            patch_body["attendees"] = [
                {"email": email} for email in coerce_to_string_list(attendees)
            ]

        # Conferencing
        conf_data, conf_params = resolve_conference_data(add_google_meet=bool(add_google_meet))
        if conf_data:
            patch_body["conferenceData"] = conf_data

        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            updated_event = dict(existing)
            updated_event.update(patch_body)
            if add_google_meet and "hangoutLink" not in updated_event:
                updated_event["hangoutLink"] = (
                    f"https://meet.google.com/{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:3]}"
                )
            self._mock_events[event_id] = updated_event
            logger.info("Mock updated calendar event: %s", event_id)
            return updated_event

        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{event_id}"
        )
        client = self.auth_helper._get_http_client()
        resp = await client.patch(url, headers=headers, params=conf_params, json=patch_body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def delete_event(self, event_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Delete an event from calendar."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            if event_id in self._mock_events:
                del self._mock_events[event_id]
                return {"status": "deleted", "event_id": event_id}
            raise KeyError(f"Event ID '{event_id}' not found.")

        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{event_id}"
        )
        client = self.auth_helper._get_http_client()
        resp = await client.delete(url, headers=headers)
        resp.raise_for_status()
        return {"status": "deleted", "event_id": event_id}

    async def query_freebusy(
        self,
        time_min: str,
        time_max: str,
        calendar_ids: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Query free/busy intervals across calendars for meeting scheduling."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        norm_time_min = normalize_calendar_time(time_min)
        norm_time_max = normalize_calendar_time(time_max)
        if not norm_time_min or not norm_time_max:
            raise ValueError("time_min and time_max are required for freebusy query.")

        cal_ids = coerce_to_string_list(calendar_ids) or [self.calendar_id or "primary"]

        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            # Compute busy intervals from mock events
            busy_slots: list[dict[str, str]] = []
            for evt in self._mock_events.values():
                evt_start = evt.get("start", {}).get("dateTime") or evt.get("start", {}).get("date")
                evt_end = evt.get("end", {}).get("dateTime") or evt.get("end", {}).get("date")
                if evt_start and evt_end:
                    if evt_start < norm_time_max and evt_end > norm_time_min:
                        busy_slots.append({"start": evt_start, "end": evt_end})

            primary_id = self.calendar_id or "primary"
            calendars_busy: dict[str, dict[str, list[dict[str, str]]]] = {}
            for cal_id in cal_ids:
                if cal_id in ("primary", primary_id):
                    calendars_busy[cal_id] = {"busy": busy_slots}
                else:
                    calendars_busy[cal_id] = {"busy": []}

            return {
                "kind": "calendar#freeBusy",
                "timeMin": norm_time_min,
                "timeMax": norm_time_max,
                "calendars": calendars_busy,
            }

        url = "https://www.googleapis.com/calendar/v3/freeBusy"
        query_body = {
            "timeMin": norm_time_min,
            "timeMax": norm_time_max,
            "items": [{"id": cid} for cid in cal_ids],
        }
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, json=query_body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    def get_tools(self) -> list[BaseTool]:
        """Return BaseTool wrapper instances for all calendar actions."""
        return [
            CalendarListEventsTool(adapter=self),
            CalendarCreateEventTool(adapter=self),
            CalendarUpdateEventTool(adapter=self),
            CalendarDeleteEventTool(adapter=self),
            CalendarQueryFreeBusyTool(adapter=self),
        ]


class CalendarListEventsTool(BaseTool):
    """Tool to list events from Google Calendar with keyword search and compact mode."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_list_events",
            description="List scheduled events from Google Calendar in chronological ascending order (earliest first). When querying upcoming/current events, time_min defaults to the current time. To search for past events or historical records, explicitly specify time_min (and optionally time_max).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Lower bound RFC3339 timestamp (e.g. '2026-09-08T00:00:00Z') or date ('2026-09-08'). Defaults to current time if omitted (returning upcoming events). If looking for past events, explicitly specify an earlier timestamp.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "Upper bound RFC3339 timestamp (e.g. '2026-09-08T23:59:59Z') or date ('2026-09-08')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to retrieve (default: 10)",
                        "default": 10,
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional keyword to search across event summary and description (e.g. '충무병원')",
                    },
                    "detailed": {
                        "type": "boolean",
                        "description": "Whether to return full event details. Default false returns a compact view to save context tokens.",
                        "default": False,
                    },
                },
                "required": [],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        time_min = kwargs.get("time_min")
        time_max = kwargs.get("time_max")
        max_results = int(kwargs.get("max_results", 10))
        query = kwargs.get("query")
        detailed = bool(kwargs.get("detailed", False))
        return await self.adapter.list_events(
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=query,
            detailed=detailed,
            user_id=user_id,
        )


class CalendarCreateEventTool(BaseTool):
    """Tool to create a new event in Google Calendar."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_create_event",
            description="Create a new event in Google Calendar with summary, start/end time (timed or all-day), timezone, attendees, and optional Google Meet conference.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title or summary of the event",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in RFC3339/ISO8601 format (e.g. '2026-09-01T15:00:00') or date for all-day ('2026-09-01')",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in RFC3339/ISO8601 format (e.g. '2026-09-01T16:00:00') or date for all-day ('2026-09-02')",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Optional IANA timezone identifier (e.g. 'Asia/Seoul', 'America/New_York')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description or meeting agenda",
                        "default": "",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list or comma-separated string of attendee email addresses",
                        "default": [],
                    },
                    "add_google_meet": {
                        "type": "boolean",
                        "description": "Whether to generate a Google Meet video conference link automatically",
                        "default": False,
                    },
                },
                "required": ["summary", "start_time", "end_time"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        summary = str(kwargs.get("summary", ""))
        start_time = str(kwargs.get("start_time", ""))
        end_time = str(kwargs.get("end_time", ""))
        description = str(kwargs.get("description", ""))
        attendees = kwargs.get("attendees")
        timezone = kwargs.get("timezone")
        add_google_meet = bool(kwargs.get("add_google_meet", False))
        return await self.adapter.create_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            attendees=attendees,
            timezone=timezone,
            add_google_meet=add_google_meet,
            user_id=user_id,
        )


class CalendarUpdateEventTool(BaseTool):
    """Tool to update an existing event in Google Calendar."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_update_event",
            description="Update an existing event in Google Calendar by event ID while preserving all unmentioned fields.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The unique event identifier to update",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional new title or summary",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Optional new start time (e.g. '2026-09-01T15:00:00' or '2026-09-01')",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Optional new end time (e.g. '2026-09-01T16:00:00' or '2026-09-02')",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Optional new IANA timezone identifier (e.g. 'Asia/Seoul')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional new description or agenda",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional replacement list or comma-separated string of attendee email addresses",
                    },
                    "add_google_meet": {
                        "type": "boolean",
                        "description": "Whether to attach a Google Meet link if not already present",
                    },
                },
                "required": ["event_id"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        event_id = str(kwargs.get("event_id", ""))
        return await self.adapter.update_event(
            event_id=event_id,
            summary=kwargs.get("summary"),
            start_time=kwargs.get("start_time"),
            end_time=kwargs.get("end_time"),
            description=kwargs.get("description"),
            attendees=kwargs.get("attendees"),
            timezone=kwargs.get("timezone"),
            add_google_meet=kwargs.get("add_google_meet"),
            user_id=user_id,
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

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        event_id = str(kwargs.get("event_id", ""))
        return await self.adapter.delete_event(event_id=event_id, user_id=user_id)


class CalendarQueryFreeBusyTool(BaseTool):
    """Tool to query schedule availability across calendars."""

    def __init__(self, adapter: GoogleCalendarAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="calendar_query_freebusy",
            description="Query free/busy intervals across calendars to find available meeting slots without scheduling conflicts.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Start of evaluation interval in RFC3339/ISO8601 format (e.g. '2026-09-01T09:00:00Z')",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of evaluation interval in RFC3339/ISO8601 format (e.g. '2026-09-01T18:00:00Z')",
                    },
                    "calendar_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List or comma-separated string of calendar identifiers to check (defaults to primary user calendar)",
                        "default": [],
                    },
                },
                "required": ["time_min", "time_max"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        time_min = str(kwargs.get("time_min", ""))
        time_max = str(kwargs.get("time_max", ""))
        calendar_ids = kwargs.get("calendar_ids")
        return await self.adapter.query_freebusy(
            time_min=time_min,
            time_max=time_max,
            calendar_ids=calendar_ids,
            user_id=user_id,
        )


__all__ = [
    "CalendarCreateEventTool",
    "CalendarDeleteEventTool",
    "CalendarListEventsTool",
    "CalendarQueryFreeBusyTool",
    "CalendarUpdateEventTool",
    "GoogleCalendarAdapter",
]
