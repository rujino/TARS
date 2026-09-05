"""Streaming event models for TARS orchestration and wire protocol serialization."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentStreamEvent(BaseModel):
    """Unified protocol-independent event emitted during agent dialogue turn execution."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(
        ...,
        description="Event type: stream_start, tool_start, tool_result, token, stream_end, error, done",
    )
    session_id: str | None = Field(default=None, description="Active session ID")
    delta: str | None = Field(default=None, description="Incremental text token delta")
    content: str | None = Field(
        default=None, description="Current accumulated text content or message"
    )
    tool: str | None = Field(default=None, description="Name of tool being executed or completed")
    call_id: str | None = Field(default=None, description="Unique tool call invocation ID")
    args: dict[str, Any] | None = Field(default=None, description="Tool invocation input arguments")
    status: str | None = Field(
        default=None, description="Tool execution status: success or error"
    )
    result: Any | None = Field(default=None, description="Tool execution result payload")
    error: str | None = Field(
        default=None, description="Error detail if tool or generation failed"
    )
    tools_used: list[str] | None = Field(
        default=None, description="List of tools utilized in this turn"
    )

    def to_sse_event(self) -> str:
        """Format as Server-Sent Event (SSE) wire protocol frame."""
        if self.type == "stream_start":
            payload = json.dumps({"session_id": self.session_id}, ensure_ascii=False)
            return f"event: stream_start\ndata: {payload}\n\n"
        elif self.type == "tool_start":
            payload = json.dumps(
                {"tool": self.tool, "call_id": self.call_id, "args": self.args},
                ensure_ascii=False,
            )
            return f"event: tool_start\ndata: {payload}\n\n"
        elif self.type == "tool_result":
            payload = json.dumps(
                {
                    "tool": self.tool,
                    "status": self.status,
                    "result": self.result,
                    "error": self.error,
                },
                ensure_ascii=False,
            )
            return f"event: tool_result\ndata: {payload}\n\n"
        elif self.type == "token":
            payload = json.dumps(
                {"content": self.content, "delta": self.delta}, ensure_ascii=False
            )
            return f"event: token\ndata: {payload}\n\n"
        elif self.type == "stream_end":
            payload = json.dumps(
                {
                    "session_id": self.session_id,
                    "content": self.content,
                    "tools_used": self.tools_used or [],
                },
                ensure_ascii=False,
            )
            return f"event: stream_end\ndata: {payload}\n\n"
        elif self.type == "error":
            payload = json.dumps({"error": self.error or self.content}, ensure_ascii=False)
            return f"event: error\ndata: {payload}\n\n"
        elif self.type == "done":
            return "event: done\ndata: [DONE]\n\n"

        return f"event: {self.type}\ndata: {self.model_dump_json(exclude_none=True)}\n\n"

    def to_ws_dict(self) -> dict[str, Any]:
        """Format as WebSocket client JSON payload."""
        data: dict[str, Any] = {"type": self.type}
        if self.session_id is not None:
            data["session_id"] = self.session_id
        if self.content is not None:
            data["content"] = self.content
        if self.delta is not None:
            data["delta"] = self.delta
        if self.tool is not None:
            data["tool"] = self.tool
        if self.call_id is not None:
            data["call_id"] = self.call_id
        if self.args is not None:
            data["args"] = self.args
        if self.status is not None:
            data["status"] = self.status
        if self.result is not None:
            data["result"] = self.result
        if self.error is not None:
            data["error"] = self.error
        if self.tools_used is not None:
            data["tools_used"] = self.tools_used
        return data


__all__ = ["AgentStreamEvent"]
