"""TARS Persona Configuration and Cognitive Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TARSConfigResponse(BaseModel):
    """Current TARS settings model."""

    model_config = ConfigDict(from_attributes=True)

    mode: str


class TARSConfigUpdateRequest(BaseModel):
    """Partial update payload for TARS configuration."""

    model_config = ConfigDict(extra="ignore")

    mode: Literal["attend", "task", "companion", "work"] | None = Field(
        default=None,
        description="Operational mode ('attend' or 'task')",
    )

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v == "companion":
            return "attend"
        if v == "work":
            return "task"
        return v


class RoleType(str, Enum):
    """Companion character operational role type."""

    SYSTEM_1_EMOTIONAL = "system_1_emotional"  # Emotional healing / mood maker (e.g. Miu)
    SYSTEM_2_TASK = "system_2_task"  # Rational task execution / reality care (e.g. Vera)
    ANALYTICAL = "analytical"  # Fact check / deep analysis
    COMPANION_ROMANCE = "companion_romance"  # Tsundere / childhood friend / romantic companion


class PersonaDefinition(BaseModel):
    """Pluggable persona definition schema for companion characters."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="Unique string identifier (e.g. 'vera', 'miu', 'luna')")
    name: str = Field(description="Display name and mention keyword (e.g. '베라', '미우')")
    title: str = Field(
        description="Role title/honorific (e.g. '수석 메이드', '견습 고양이 메이드')"
    )
    role: RoleType = Field(description="Core functional role type")
    avatar: str | None = Field(default=None, description="Avatar image URI or URL")
    speech_style: str = Field(description="Speech style instructions and honorific guidelines")
    relationship_stance: str = Field(
        description="Relationship stance and care philosophy towards master"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Permitted execution tool names"
    )
    prompt_template: str = Field(description="Jinja2 or string template for persona system prompt")
    read_jitter_range: tuple[float, float] = Field(
        default=(0.2, 0.5),
        description="Range of read-receipt delay jitter in seconds (min, max)",
    )
    is_builtin: bool = Field(default=False, description="Whether this persona is built into TARS")

    def __init__(self, **data: Any) -> None:
        if "role_type" in data and "role" not in data:
            data["role"] = data.pop("role_type")
        if "avatar_url" in data and "avatar" not in data:
            data["avatar"] = data.pop("avatar_url")
        if "system_prompt_template" in data and "prompt_template" not in data:
            data["prompt_template"] = data.pop("system_prompt_template")
        super().__init__(**data)

    @field_validator("read_jitter_range")
    @classmethod
    def validate_jitter(cls, v: tuple[float, float]) -> tuple[float, float]:
        if len(v) != 2:
            raise ValueError("read_jitter_range must be a tuple of two floats (min, max).")
        min_j, max_j = v
        if min_j < 0 or max_j < 0:
            raise ValueError("read_jitter_range values cannot be negative.")
        if min_j > max_j:
            raise ValueError("read_jitter_range min value cannot exceed max value.")
        return v

    @property
    def role_type(self) -> RoleType:
        return self.role

    @property
    def avatar_url(self) -> str | None:
        return self.avatar

    @property
    def system_prompt_template(self) -> str:
        return self.prompt_template


class SubconsciousStatePayload(BaseModel):
    """Tier 1 TARS unconscious psychological truth extraction (objective master state)."""

    context_summary: str = Field(
        description="Micro-narrative summary of recent turns and emotional causes",
    )
    master_state: str = Field(
        description="Master's current physical and emotional state (e.g. sleep-deprived, burnout, defensive)",
    )
    expected_reaction: str | None = Field(
        default=None,
        description="Predicted user reaction to this turn's dialogue (Theory of Mind)",
    )
    prediction_feedback: str | None = Field(
        default=None,
        description="Evaluation of previous turn's prediction error vs actual user response",
    )


class CharacterInnerState(BaseModel):
    """Tier 2 conscious inner monologue autonomously formed by an active companion agent."""

    speaker_id: str = Field(description="Persona identifier (e.g. 'vera', 'miu')")
    my_vibe: str = Field(description="Inner emotion transition and residual sentiment")
    my_agenda: str = Field(
        description="Psychological agenda or conversational strategy for this turn"
    )


class RoutingPattern(str, Enum):
    """Conversation routing patterns in multi-agent companion dialogue."""

    SOLO = "SOLO"
    TAG_TEAM_REMEDIATION = "TAG_TEAM_REMEDIATION"
    DEBATE_BANTER = "DEBATE_BANTER"
    GUARDRAIL_INTERVENTION = "GUARDRAIL_INTERVENTION"


class TurnRoutingDecision(BaseModel):
    """Deterministic routing decision determining which companion(s) speak this turn."""

    pattern: RoutingPattern = Field(description="Routing conversation pattern")
    primary_speaker_id: str = Field(description="First/primary speaker persona identifier")
    secondary_speaker_id: str | None = Field(
        default=None,
        description="Second speaker persona identifier if multi-speaker pattern",
    )
    dialogue_tone: str = Field(
        default="neutral",
        description="Overall tone direction for this turn",
    )
    turn_intent: str = Field(
        default="dialogue",
        description="High-level communicative intent for this turn",
    )
    reason: str | None = Field(
        default=None,
        description="Diagnostic explanation for this routing decision",
    )


class DefaultSpeakerId:
    """Standard persona identifier constants."""

    MASTER = "master"
    VERA = "vera"
    MIU = "miu"


class GroupChatMessage(BaseModel):
    """Multi-agent companion group chat message envelope."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(description="Chat session identifier")
    sender_id: str = Field(description="Sender identifier ('master' or persona ID)")
    recipients: list[str] = Field(
        default_factory=lambda: [DefaultSpeakerId.VERA, DefaultSpeakerId.MIU],
        description="List of recipient persona IDs active in the group session",
    )
    target_speaker_id: str | None = Field(
        default=None,
        description="Explicitly targeted recipient persona ID if mentioned",
    )
    content: str = Field(description="Message body text")
    unread_count: int | None = Field(
        default=None,
        description="Calculated or explicit count of unread recipients",
    )
    is_interrupted: bool = Field(
        default=False,
        description="Whether streaming was aborted by barge-in",
    )
    interrupted_at_token_count: int | None = Field(
        default=None,
        description="Token index where interruption occurred",
    )
    reply_to_id: str | None = Field(
        default=None,
        description="Identifier of message being directly replied to",
    )
    read_by: list[str] = Field(
        default_factory=list,
        description="List of persona IDs that have marked this message as read",
    )
    inner_state_snapshot: CharacterInnerState | None = Field(
        default=None,
        description="Snapshot of speaker's autonomous inner state when emitting this message",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp",
    )

    def model_post_init(self, __context: Any) -> None:
        if self.unread_count is None:
            self.unread_count = max(0, len(self.recipients) - len(self.read_by))


class CognitiveRoutingPayload(BaseModel):
    """Unified cognitive state output wrapping subconscious truth and routing decision."""

    subconscious: SubconsciousStatePayload
    routing_decision: TurnRoutingDecision


__all__ = [
    "CharacterInnerState",
    "CognitiveRoutingPayload",
    "DefaultSpeakerId",
    "GroupChatMessage",
    "PersonaDefinition",
    "RoleType",
    "RoutingPattern",
    "SubconsciousStatePayload",
    "TARSConfigResponse",
    "TARSConfigUpdateRequest",
    "TurnRoutingDecision",
]
