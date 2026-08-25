"""TARS Persona Configuration Pydantic schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TARSConfigResponse(BaseModel):
    """Current TARS persona settings model."""

    model_config = ConfigDict(from_attributes=True)

    humor_level: float
    honesty_level: float
    mode: str


class TARSConfigUpdateRequest(BaseModel):
    """Partial update payload for TARS persona configuration."""

    model_config = ConfigDict(extra="forbid")

    humor_level: float | None = Field(
        default=None,
        description="Humor index in range 0.0 to 1.0 or 0 to 100",
    )
    honesty_level: float | None = Field(
        default=None,
        description="Honesty index in range 0.0 to 1.0 or 0 to 100",
    )
    mode: Literal["companion", "work"] | None = Field(
        default=None,
        description="Operational mode ('companion' or 'work')",
    )

    @field_validator("humor_level", "honesty_level")
    @classmethod
    def validate_levels(cls, v: float | None) -> float | None:
        if v is None:
            return None
        # Normalize 0-100 percentage to 0.0-1.0 if needed
        if 1.0 < v <= 100.0:
            v = v / 100.0
        if v < 0.0 or v > 1.0:
            raise ValueError("Level parameters must be between 0.0 and 1.0 (or 0 and 100)")
        return round(float(v), 4)


__all__ = [
    "TARSConfigResponse",
    "TARSConfigUpdateRequest",
]
