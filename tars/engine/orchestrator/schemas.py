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
    status: str | None = Field(default=None, description="Tool execution status: success or error")
    result: Any | None = Field(default=None, description="Tool execution result payload")
    error: str | None = Field(default=None, description="Error detail if tool or generation failed")
    tools_used: list[str] | None = Field(
        default=None, description="List of tools utilized in this turn"
    )
    engine: str | None = Field(
        default=None, description="Engine that produced the turn response (gemini or slm)"
    )
    model_name: str | None = Field(
        default=None, description="Model identifier that produced the turn response"
    )
    title: str | None = Field(default=None, description="Updated session title")
    speaker: str | None = Field(
        default=None, description="Active speaker persona ID (e.g., vera, miu)"
    )
    avatar: str | None = Field(
        default=None, description="Avatar image URL or asset path for the speaker"
    )
    turn_epoch: int | None = Field(
        default=None,
        description="Monotonic turn generation epoch for concurrency arbitration",
    )
    turn_state: str | None = Field(
        default=None,
        description="Turn state metadata (e.g., primary, secondary, monologue)",
    )

    def to_sse_event(self) -> str:
        """Format as Server-Sent Event (SSE) wire protocol frame."""
        if self.type == "stream_start":
            payload_dict: dict[str, Any] = {"session_id": self.session_id}
            if self.speaker is not None:
                payload_dict["speaker"] = self.speaker
            if self.avatar is not None:
                payload_dict["avatar"] = self.avatar
            if self.turn_epoch is not None:
                payload_dict["turn_epoch"] = self.turn_epoch
            if self.turn_state is not None:
                payload_dict["turn_state"] = self.turn_state
            payload = json.dumps(payload_dict, ensure_ascii=False)
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
            payload_dict = {"content": self.content, "delta": self.delta}
            if self.speaker is not None:
                payload_dict["speaker"] = self.speaker
            if self.avatar is not None:
                payload_dict["avatar"] = self.avatar
            if self.turn_epoch is not None:
                payload_dict["turn_epoch"] = self.turn_epoch
            if self.turn_state is not None:
                payload_dict["turn_state"] = self.turn_state
            payload = json.dumps(payload_dict, ensure_ascii=False)
            return f"event: token\ndata: {payload}\n\n"
        elif self.type == "stream_end":
            payload_dict = {
                "session_id": self.session_id,
                "content": self.content,
                "tools_used": self.tools_used or [],
            }
            if self.title is not None:
                payload_dict["title"] = self.title
            if self.engine is not None:
                payload_dict["engine"] = self.engine
            if self.model_name is not None:
                payload_dict["model_name"] = self.model_name
            if self.speaker is not None:
                payload_dict["speaker"] = self.speaker
            if self.avatar is not None:
                payload_dict["avatar"] = self.avatar
            if self.turn_epoch is not None:
                payload_dict["turn_epoch"] = self.turn_epoch
            if self.turn_state is not None:
                payload_dict["turn_state"] = self.turn_state
            payload = json.dumps(payload_dict, ensure_ascii=False)
            return f"event: stream_end\ndata: {payload}\n\n"
        elif self.type == "error":
            err_msg = self.error or self.content or "Stream error occurred"
            payload_dict = {"error": err_msg, "message": err_msg}
            if self.speaker is not None:
                payload_dict["speaker"] = self.speaker
            if self.avatar is not None:
                payload_dict["avatar"] = self.avatar
            if self.turn_epoch is not None:
                payload_dict["turn_epoch"] = self.turn_epoch
            if self.turn_state is not None:
                payload_dict["turn_state"] = self.turn_state
            payload = json.dumps(payload_dict, ensure_ascii=False)
            return f"event: error\ndata: {payload}\n\n"
        elif self.type == "done":
            return "event: done\ndata: [DONE]\n\n"

        return f"event: {self.type}\ndata: {self.model_dump_json(exclude_none=True)}\n\n"

    def to_ws_dict(self) -> dict[str, Any]:
        """Format as WebSocket client JSON payload."""
        data: dict[str, Any] = {"type": self.type}
        if self.session_id is not None:
            data["session_id"] = self.session_id
        if self.title is not None:
            data["title"] = self.title
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
            data["message"] = self.error
        if self.tools_used is not None:
            data["tools_used"] = self.tools_used
        if self.engine is not None:
            data["engine"] = self.engine
        if self.model_name is not None:
            data["model_name"] = self.model_name
        if self.speaker is not None:
            data["speaker"] = self.speaker
        if self.avatar is not None:
            data["avatar"] = self.avatar
        if self.turn_epoch is not None:
            data["turn_epoch"] = self.turn_epoch
        if self.turn_state is not None:
            data["turn_state"] = self.turn_state
        return data


__all__ = ["AgentStreamEvent"]
