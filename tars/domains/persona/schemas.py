"""TARS Persona Configuration Pydantic schemas."""

from __future__ import annotations

from typing import Literal

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


__all__ = [
    "TARSConfigResponse",
    "TARSConfigUpdateRequest",
]
