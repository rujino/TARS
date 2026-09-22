"""Data models for proactive scheduling."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from tars.domains.proactive.schemas import ScheduleType


class ScheduledJobInfo(BaseModel):
    """Metadata representing an active or restored scheduled job."""

    model_config = ConfigDict(extra="ignore")

    entry_id: str
    user_id: str
    schedule_type: ScheduleType
    okf_id: str | None = None
    next_run_at: datetime
    is_active: bool


__all__ = ["ScheduledJobInfo"]
