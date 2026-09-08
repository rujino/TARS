"""Gmail API Adapter and Tools for TARS.

Supports:
- gmail_search_messages: Search emails with query filters & thread awareness
- gmail_get_message: Retrieve full message detail by ID
- gmail_get_thread: Retrieve complete conversation thread with ball-in-court ownership analysis
- gmail_send_message: Send an email message (supports HTML, threading, attachments, and quoting)
- gmail_draft_message: Create a safe draft email for human-in-the-loop review
- Deterministic in-memory mock mode for offline testing
"""

from __future__ import annotations

import base64
import email.message
import logging
import mimetypes
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from tars.tools.base import BaseTool
from tars.tools.google.auth import GoogleAuthHelper

logger = logging.getLogger("tars.tools.google.gmail")


class _HTMLTextExtractor(HTMLParser):
    """Simple stdlib HTML to plain text converter."""

    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip = True
        elif tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "li"):
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False
        elif tag in ("p", "div"):
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        raw = "".join(self._text)
        return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def html_to_plain_text(html_content: str) -> str:
    """Convert HTML string to clean plain text."""
    try:
        parser = _HTMLTextExtractor()
        parser.feed(html_content)
        return parser.get_text()
    except Exception:
        return html_content


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
        self._mock_drafts: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        """Close underlying authentication and HTTP resources."""
        if hasattr(self.auth_helper, "close"):
            await self.auth_helper.close()

    async def aclose(self) -> None:
        """Async close alias."""
        await self.close()

    async def search_messages(
        self,
        query: str,
        max_results: int = 5,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search messages with query filter, returning metadata and web interface links."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            q_lower = query.lower()
            results: list[dict[str, Any]] = []
            for msg in self._mock_messages.values():
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
                    th_id = msg.get("threadId", msg["id"])
                    results.append(
                        {
                            "id": msg["id"],
                            "threadId": th_id,
                            "from": msg.get("from", ""),
                            "subject": msg.get("subject", ""),
                            "snippet": msg.get("snippet", ""),
                            "date": msg.get("date", ""),
                            "web_link": f"https://mail.google.com/mail/u/0/#inbox/{th_id}",
                        }
                    )
            return results[:max_results]

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params: dict[str, str | int] = {"q": query, "maxResults": max_results}
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        messages: list[dict[str, Any]] = data.get("messages", [])
        return messages

    async def get_message(
        self, message_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve message details by ID."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            if message_id in self._mock_messages:
                return self._mock_messages[message_id]
            raise KeyError(f"Gmail message ID '{message_id}' not found.")

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def get_thread(
        self,
        thread_id: str,
        include_analysis: bool = True,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve full conversation thread with ownership analysis."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            thread_messages = [
                msg
                for msg in self._mock_messages.values()
                if msg.get("threadId") == thread_id or msg.get("id") == thread_id
            ]
            if not thread_messages:
                raise KeyError(f"Gmail thread ID '{thread_id}' not found.")

            # Sort chronologically
            thread_messages.sort(key=lambda m: m.get("date", ""))
            participants = list({m.get("from") for m in thread_messages if m.get("from")})
            last_msg = thread_messages[-1]
            last_sender = last_msg.get("from", "")

            # Ownership verdict: If last sender is TARS/authenticated user, ball is in other's court
            is_self = "tars" in last_sender.lower()
            ball_in_court = "waiting_for_reply" if is_self else "action_required"

            res: dict[str, Any] = {
                "thread_id": thread_id,
                "messages": thread_messages,
                "message_count": len(thread_messages),
            }
            if include_analysis:
                res["analysis"] = {
                    "last_sender": last_sender,
                    "ball_in_court_of": ball_in_court,
                    "participants": participants,
                }
            return res

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}"
        client = self.auth_helper._get_http_client()
        resp = await client.get(url, headers=headers, params={"format": "full"})
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    def _assemble_mime_message(
        self,
        to: str,
        subject: str,
        body: str,
        body_format: str = "plain",
        cc: str | None = None,
        bcc: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> email.message.EmailMessage:
        """Assemble a complete RFC 2822 MIME EmailMessage object."""
        msg = email.message.EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        if body_format == "html":
            plain_fallback = html_to_plain_text(body)
            msg.set_content(plain_fallback)
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)

        # Process attachments if provided
        for att in attachments or []:
            file_path = att.get("path")
            content_b64 = att.get("content")
            filename = att.get("filename")
            mime_type = att.get("mime_type")

            data = None
            if file_path:
                p = Path(file_path)
                if p.is_file():
                    data = p.read_bytes()
                    if not filename:
                        filename = p.name
                    if not mime_type:
                        mime_type, _ = mimetypes.guess_type(str(p))
            elif content_b64:
                try:
                    data = base64.b64decode(content_b64)
                except Exception as exc:
                    logger.warning("Failed to decode base64 attachment: %s", exc)

            if data:
                main_type, sub_type = (
                    mime_type.split("/", 1)
                    if mime_type and "/" in mime_type
                    else ("application", "octet-stream")
                )
                msg.add_attachment(
                    data,
                    maintype=main_type,
                    subtype=sub_type,
                    filename=filename or "attachment",
                )

        return msg

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        body_format: str = "plain",
        cc: str | None = None,
        bcc: str | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        quote_original: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Send an email message via Gmail with HTML, attachments, and thread reply support."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        effective_body = body

        if quote_original and thread_id and (self.auth_helper.mock_mode or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"):
            matching = [m for m in self._mock_messages.values() if m.get("threadId") == thread_id]
            if matching:
                orig = matching[-1]
                quote = f"\n\nOn {orig.get('date', '')}, {orig.get('from', 'sender')} wrote:\n> " + orig.get("body", "").replace("\n", "\n> ")
                effective_body = body + quote

        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            msg_id = f"msg_{uuid.uuid4().hex[:8]}"
            th_id = thread_id or f"th_{uuid.uuid4().hex[:8]}"
            sent_msg = {
                "id": msg_id,
                "threadId": th_id,
                "from": "tars@endurance.space",
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "subject": subject,
                "snippet": effective_body[:50],
                "body": effective_body,
                "body_format": body_format,
                "date": "2026-08-26T00:00:00Z",
                "is_unread": False,
                "status": "sent",
            }
            self._mock_messages[msg_id] = sent_msg
            logger.info("Mock sent email: %s to %s ('%s')", msg_id, to, subject)
            return {"id": msg_id, "threadId": th_id, "status": "sent", "to": to, "subject": subject}

        mime_msg = self._assemble_mime_message(
            to=to,
            subject=subject,
            body=effective_body,
            body_format=body_format,
            cc=cc,
            bcc=bcc,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
        )
        raw_b64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        payload: dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            payload["threadId"] = thread_id

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        res_data: dict[str, Any] = resp.json()
        return res_data

    async def draft_message(
        self,
        to: str,
        subject: str,
        body: str,
        body_format: str = "plain",
        cc: str | None = None,
        bcc: str | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft message in Gmail for user inspection before sending."""
        headers = await self.auth_helper.get_auth_headers(user_id=user_id)
        if (
            self.auth_helper.mock_mode
            or headers.get("Authorization") == "Bearer mock_google_oauth2_access_token"
        ):
            draft_id = f"draft_{uuid.uuid4().hex[:8]}"
            th_id = thread_id or f"th_{uuid.uuid4().hex[:8]}"
            draft_entry = {
                "id": draft_id,
                "message": {
                    "id": f"msg_draft_{uuid.uuid4().hex[:6]}",
                    "threadId": th_id,
                    "to": to,
                    "subject": subject,
                    "body": body,
                    "body_format": body_format,
                    "cc": cc,
                },
                "status": "draft_created",
            }
            self._mock_drafts[draft_id] = draft_entry
            logger.info("Mock created email draft: %s ('%s')", draft_id, subject)
            return {"id": draft_id, "threadId": th_id, "status": "draft_created", "to": to, "subject": subject}

        mime_msg = self._assemble_mime_message(
            to=to,
            subject=subject,
            body=body,
            body_format=body_format,
            cc=cc,
            bcc=bcc,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
        )
        raw_b64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        msg_payload: dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            msg_payload["threadId"] = thread_id

        url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
        client = self.auth_helper._get_http_client()
        resp = await client.post(url, headers=headers, json={"message": msg_payload})
        resp.raise_for_status()
        res_data: dict[str, Any] = resp.json()
        return res_data

    def get_tools(self) -> list[BaseTool]:
        """Return BaseTool wrapper instances for all Gmail actions."""
        return [
            GmailSearchMessagesTool(adapter=self),
            GmailGetMessageTool(adapter=self),
            GmailGetThreadTool(adapter=self),
            GmailSendMessageTool(adapter=self),
            GmailDraftMessageTool(adapter=self),
        ]


class GmailSearchMessagesTool(BaseTool):
    """Tool to search Gmail messages."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_search_messages",
            description="Search emails in Gmail matching query keywords and filters (e.g. 'from:cooper', 'is:unread', 'subject:Gargantua'). Returns message ID, thread ID, and web link.",
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

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        query = str(kwargs.get("query", ""))
        max_results = int(kwargs.get("max_results", 5))
        return await self.adapter.search_messages(
            query=query, max_results=max_results, user_id=user_id
        )


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

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        message_id = str(kwargs.get("message_id", ""))
        return await self.adapter.get_message(message_id=message_id, user_id=user_id)


class GmailGetThreadTool(BaseTool):
    """Tool to retrieve an entire email conversation thread with ownership analysis."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_get_thread",
            description="Retrieve an entire conversation thread by thread ID, including chronological messages, participant list, and ball-in-court ownership analysis (who owes a reply).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "thread_id": {
                        "type": "string",
                        "description": "The unique Gmail conversation thread ID",
                    },
                    "include_analysis": {
                        "type": "boolean",
                        "description": "Whether to calculate ball-in-court ownership and participant stats",
                        "default": True,
                    },
                },
                "required": ["thread_id"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        thread_id = str(kwargs.get("thread_id", ""))
        include_analysis = bool(kwargs.get("include_analysis", True))
        return await self.adapter.get_thread(
            thread_id=thread_id,
            include_analysis=include_analysis,
            user_id=user_id,
        )


class GmailSendMessageTool(BaseTool):
    """Tool to send an email message via Gmail."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_send_message",
            description="Send an email message to recipients with subject, plain or HTML body, threading headers, attachments, and optional original quotation.",
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
                        "description": "Body content of the email",
                    },
                    "body_format": {
                        "type": "string",
                        "enum": ["plain", "html"],
                        "description": "Body format: 'plain' for plaintext or 'html' for HTML content",
                        "default": "plain",
                    },
                    "cc": {
                        "type": "string",
                        "description": "Optional CC recipient email address",
                    },
                    "bcc": {
                        "type": "string",
                        "description": "Optional BCC recipient email address",
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Optional Gmail thread ID to reply within an existing conversation",
                    },
                    "in_reply_to": {
                        "type": "string",
                        "description": "Optional Message-ID to explicitly link the reply",
                    },
                    "references": {
                        "type": "string",
                        "description": "Optional space-separated list of Message-IDs for threading context (RFC 2822 References header)",
                    },
                    "quote_original": {
                        "type": "boolean",
                        "description": "Whether to append quoted original message when replying in a thread",
                        "default": False,
                    },
                    "attachments": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional list of attachment objects: [{'path': '/path/to/file'}, {'content': '<base64>', 'filename': 'doc.pdf'}]",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        to = str(kwargs.get("to", ""))
        subject = str(kwargs.get("subject", ""))
        body = str(kwargs.get("body", ""))
        body_format = str(kwargs.get("body_format", "plain"))
        cc = kwargs.get("cc")
        bcc = kwargs.get("bcc")
        thread_id = kwargs.get("thread_id")
        in_reply_to = kwargs.get("in_reply_to")
        references = kwargs.get("references")
        attachments = kwargs.get("attachments")
        quote_original = bool(kwargs.get("quote_original", False))
        return await self.adapter.send_message(
            to=to,
            subject=subject,
            body=body,
            body_format=body_format,
            cc=cc,
            bcc=bcc,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
            quote_original=quote_original,
            user_id=user_id,
        )


class GmailDraftMessageTool(BaseTool):
    """Tool to create a safe email draft in Gmail without sending."""

    def __init__(self, adapter: GmailAdapter) -> None:
        self.adapter = adapter
        super().__init__(
            name="gmail_draft_message",
            description="Create an email draft in Gmail. Recommended when you want user inspection and confirmation before actually sending the email.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject line of the draft email",
                    },
                    "body": {
                        "type": "string",
                        "description": "Body content of the draft",
                    },
                    "body_format": {
                        "type": "string",
                        "enum": ["plain", "html"],
                        "description": "Body format: 'plain' or 'html'",
                        "default": "plain",
                    },
                    "cc": {
                        "type": "string",
                        "description": "Optional CC recipient email address",
                    },
                    "bcc": {
                        "type": "string",
                        "description": "Optional BCC recipient email address",
                    },
                    "thread_id": {
                        "type": "string",
                        "description": "Optional Gmail thread ID to associate the draft with",
                    },
                    "in_reply_to": {
                        "type": "string",
                        "description": "Optional Message-ID to associate the draft with",
                    },
                    "references": {
                        "type": "string",
                        "description": "Optional space-separated list of Message-IDs for threading context",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional list of attachment objects",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        )

    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        to = str(kwargs.get("to", ""))
        subject = str(kwargs.get("subject", ""))
        body = str(kwargs.get("body", ""))
        body_format = str(kwargs.get("body_format", "plain"))
        cc = kwargs.get("cc")
        bcc = kwargs.get("bcc")
        thread_id = kwargs.get("thread_id")
        in_reply_to = kwargs.get("in_reply_to")
        references = kwargs.get("references")
        attachments = kwargs.get("attachments")
        return await self.adapter.draft_message(
            to=to,
            subject=subject,
            body=body,
            body_format=body_format,
            cc=cc,
            bcc=bcc,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
            user_id=user_id,
        )


__all__ = [
    "GmailAdapter",
    "GmailDraftMessageTool",
    "GmailGetMessageTool",
    "GmailGetThreadTool",
    "GmailSearchMessagesTool",
    "GmailSendMessageTool",
    "html_to_plain_text",
]
