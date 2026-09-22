"""Proactive domain Pydantic v2 schemas and payload definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScheduleType(StrEnum):
    """Classification of proactive utterance triggers."""

    REVIEW_REMINDER = "review_reminder"              # 학습 복습 리마인드
    DEADLINE_ALERT = "deadline_alert"                # 기한 임박 알림
    CONTEXT_FOLLOWUP = "context_followup"            # 대화 맥락 연속성 후속 발화
    ROUTINE_REINFORCEMENT = "routine_reinforcement"  # 사용자 루틴 강화


class ProactiveMessageStatus(StrEnum):
    """Lifecycle status of a proactive message."""

    PENDING = "pending"
    DELIVERED = "delivered"
    READ = "read"
    DISMISSED = "dismissed"


class ProactivePayload(BaseModel):
    """Platform-agnostic proactive utterance payload.

    All delivery channels (WebSocket, FCM, Inbox) serialize and exchange this structure.
    Clients receive this payload and render it natively without backend platform couplings.
    """

    model_config = ConfigDict(extra="ignore")

    message_id: str = Field(..., description="Unique UUID of the ProactiveMessage")
    persona_id: str = Field(..., description="ID of the speaking persona (e.g. 'miu', 'vera')")
    schedule_type: ScheduleType = Field(..., description="Type of proactive trigger")
    content: str = Field(..., description="Utterance body message")
    okf_id: str | None = Field(default=None, description="Associated OKF document ID for deep linking")
    scheduled_at_utc: str = Field(
        ...,
        description="ISO 8601 UTC timestamp string. Client is responsible for local timezone presentation.",
    )


class ProactiveMessageResponse(BaseModel):
    """API response model representing a proactive message entity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    persona_id: str
    schedule_type: str
    okf_id: str | None
    message_content: str
    score: float
    status: str
    scheduled_at: datetime
    delivered_at: datetime | None
    created_at: datetime


class DeviceTokenRegisterRequest(BaseModel):
    """Request payload to register or refresh a client device push token."""

    token: str = Field(..., min_length=1, max_length=512, description="FCM device registration token")
    platform: str = Field(default="web", description="Device platform: 'web' | 'ios' | 'android'")
    device_name: str | None = Field(default=None, max_length=128, description="Optional device descriptor")


class DeviceTokenResponse(BaseModel):
    """API response model for device token registration."""

    id: str
    platform: str
    device_name: str | None
    is_active: bool
    created_at: datetime


class ProactiveSettingsResponse(BaseModel):
    """API response model for user proactive settings."""

    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    max_daily_proactive: int
    quiet_hours_start: int | None
    quiet_hours_end: int | None
    timezone: str
    enabled_types: list[str]


class ProactiveSettingsUpdate(BaseModel):
    """Request payload to update user proactive preferences."""

    is_enabled: bool | None = None
    max_daily_proactive: int | None = Field(default=None, ge=1, le=10)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    timezone: str | None = Field(default=None, max_length=64)
    enabled_types: list[ScheduleType] | None = None


__all__ = [
    "DeviceTokenRegisterRequest",
    "DeviceTokenResponse",
    "ProactiveMessageResponse",
    "ProactiveMessageStatus",
    "ProactivePayload",
    "ProactiveSettingsResponse",
    "ProactiveSettingsUpdate",
    "ScheduleType",
]
