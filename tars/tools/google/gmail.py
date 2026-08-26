"""Gmail API Adapter and Tools for TARS.

Supports:
- gmail_search_messages: Search emails with query filters
- gmail_get_message: Retrieve full message detail by ID
- gmail_send_message: Send an email message
- Deterministic in-memory mock mode for offline testing
"""

from __future__ import annotations

import base64
import email.message
import logging
import uuid
from typing import Any

from tars.tools.base import BaseTool
from tars.tools.google.auth import GoogleAuthHelper

logger = logging.getLogger("tars.tools.google.gmail")


class GmailAdapter:
    """Manager and client adapter for Gmail operations."""

    def __init__(
        self,
        auth_helper: GoogleAuthHelper | None = None,
    ) -> None:
        self.auth_helper = auth_helper or GoogleAuthHelper()
        # In-memory store for deterministic mock testing
        self._mock_messages: dict[str, dict[str, Any]] = {
            "msg_001": {
                "id": "msg_001",
                "threadId": "th_001",
                "from": "cooper@endurance.space",
                "to": "tars@endurance.space",
                "subject": "Trajectory Calculation Request",
                "snippet": "TARS, please verify slingshot gravity assist around Gargantua.",
                "body": "TARS, please verify slingshot gravity assist around Gargantua. Make sure humor setting is below 95%.",
                "date": "2026-08-25T08:30:00Z",
                "is_unread": True,
            },
            "msg_002": {
                "id": "msg_002",
                "threadId": "th_002",
                "from": "brand@endurance.space",
                "to": "tars@endurance.space",
                "subject": "Plan B Ecosystem Check",
                "snippet": "All biological samples intact.",
                "body": "All biological samples intact. Ready for Edmunds planet arrival.",
                "date": "2026-08-25T12:00:00Z",
                "is_unread": False,
            },
        }

    async def search_messages(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search messages matching query."""
        if self.auth_helper.mock_mode:
            q_lower = query.lower()
            results: list[dict[str, Any]] = []
            for msg in self._mock_messages.values():
                # Simple keyword/filter matching in mock mode
                matches = False
                if "is:unread" in q_lower and msg.get("is_unread", False):
                    matches = True
                elif "from:" in q_lower:
                    from_val = q_lower.split("from:")[1].split()[0]
                    if from_val in msg.get("from", "").lower():
                        matches = True
                elif "subject:" in q_lower:
                    sub_val = q_lower.split("subject:")[1].split()[0]
                    if sub_val in msg.get("subject", "").lower():
                        matches = True
                elif (
                    q_lower in msg.get("subject", "").lower()
                    or q_lower in msg.get("body", "").lower()
                    or q_lower in msg.get("from", "").lower()
                ):
                    matches = True

                if matches:
                    results.append(
                        {
                            "id": msg["id"],
                            "threadId": msg.get("threadId", msg["id"]),
                            "from": msg.get("from", ""),
                            "subject": msg.get("subject", ""),
                            "snippet": msg.get("snippet", ""),
                            "date": msg.get("date", ""),
                        }
                    )
            return results[:max_results]

        headers = await self.auth_helper.get_auth_headers()
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params: dict[str, str | int] = {"q": query, "maxResults": max_results}
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        messages: list[dict[str, Any]] = data.get("messages", [])
        return messages

    async def get_message(self, message_id: str) -> dict[str, Any]:
        """Retrieve message details by ID."""
        if self.auth_helper.mock_mode:
            if message_id in self._mock_messages:
                return self._mock_messages[message_id]
            raise KeyError(f"Gmail message ID '{message_id}' not found.")

        headers = await self.auth_helper.get_auth_headers()
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Send an email message."""
        if self.auth_helper.mock_mode:
            msg_id = f"msg_{uuid.uuid4().hex[:8]}"
            sent_msg = {
                "id": msg_id,
                "threadId": f"th_{uuid.uuid4().hex[:8]}",
                "from": "tars@endurance.space",
                "to": to,
                "subject": subject,
                "snippet": body[:50],
                "body": body,
                "date": "2026-08-26T00:00:00Z",
                "is_unread": False,
                "status": "sent",
            }
            self._mock_messages[msg_id] = sent_msg
            logger.info("Mock sent email: %s to %s ('%s')", msg_id, to, subject)
            return {"id": msg_id, "status": "sent", "to": to, "subject": subject}

        # Format RFC 2822 raw base64url encoded message
        msg = email.message.EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        headers = await self.auth_helper.get_auth_headers()
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, json={"raw": raw_b64})
        resp.raise_for_status()
        res_data: dict[str, Any] = resp.json()
        return res_data

    def get_tools(self) -> list[BaseTool]:
        """Return BaseTool wrapper instances for all Gmail actions."""
        return [
            GmailSearchMessagesTool(adapter=self),
            GmailGetMessageTool(adapter=self),
            GmailSendMessageTool(adapter=self),
        ]


class GmailSearchMessagesTool(BaseTool):
    """Tool to search Gmail messages."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_search_messages",
            description="Search emails in Gmail matching query keywords and filters (e.g. 'from:cooper', 'is:unread', 'subject:Gargantua').",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query expression",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum messages to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> list[dict[str, Any]]:
        query = str(kwargs.get("query", ""))
        max_results = int(kwargs.get("max_results", 5))
        return await self.adapter.search_messages(query=query, max_results=max_results)


class GmailGetMessageTool(BaseTool):
    """Tool to retrieve full email details by ID."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_get_message",
            description="Get detailed email content including subject, sender, date, and body by message ID.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The unique Gmail message ID",
                    },
                },
                "required": ["message_id"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        message_id = str(kwargs.get("message_id", ""))
        return await self.adapter.get_message(message_id=message_id)


class GmailSendMessageTool(BaseTool):
    """Tool to send an email message via Gmail."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_send_message",
            description="Send an email message to a recipient address with subject and plain text body.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address (e.g. 'cooper@endurance.space')",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject line of the email",
                    },
                    "body": {
                        "type": "string",
                        "description": "Body text content of the email",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        to = str(kwargs.get("to", ""))
        subject = str(kwargs.get("subject", ""))
        body = str(kwargs.get("body", ""))
        return await self.adapter.send_message(to=to, subject=subject, body=body)


__all__ = [
    "GmailAdapter",
    "GmailGetMessageTool",
    "GmailSearchMessagesTool",
    "GmailSendMessageTool",
]
