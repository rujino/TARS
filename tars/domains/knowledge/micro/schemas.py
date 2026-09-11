"""TARS Tier 1 Micro Fact Layer Data Models.

Represents atomic user facts, preferences, identity attributes, and short-term states.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class MicroFact(BaseModel):
    """Atomic fact or preference slot."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(..., min_length=1, max_length=128, description="Fact slot key (e.g. coffee_pref)")
    value: str = Field(..., description="Fact value or natural language statement")
    category: str = Field(default="preference", description="Category: preference | profile | state | rule")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last updated timestamp"
    )

    def to_prompt_line(self) -> str:
        """Format as a compact natural language fact for prompt injection."""
        return f"- [{self.category.upper()}] {self.key}: {self.value}"


class UserMicroFactProfile(BaseModel):
    """Collection of micro facts representing the user's personal context profile."""

    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(..., description="Owner user ID")
    facts: dict[str, MicroFact] = Field(default_factory=dict, description="Map of key -> MicroFact")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last profile update timestamp"
    )

    def set_fact(self, key: str, value: str, category: str = "preference", confidence: float = 1.0) -> MicroFact:
        clean_key = key.strip().lower()
        fact = MicroFact(
            key=clean_key,
            value=value.strip(),
            category=category.strip().lower(),
            confidence=confidence,
            updated_at=datetime.now(UTC),
        )
        self.facts[clean_key] = fact
        self.updated_at = datetime.now(UTC)
        return fact

    def get_fact(self, key: str) -> MicroFact | None:
        return self.facts.get(key.strip().lower())

    def remove_fact(self, key: str) -> bool:
        clean_key = key.strip().lower()
        if clean_key in self.facts:
            del self.facts[clean_key]
            self.updated_at = datetime.now(UTC)
            return True
        return False

    def format_for_prompt(self, max_facts: int = 20) -> str:
        """Generate a compact block of bullet points for LLM prompt injection."""
        if not self.facts:
            return ""

        lines = [
            fact.to_prompt_line()
            for fact in sorted(self.facts.values(), key=lambda f: f.updated_at, reverse=True)[:max_facts]
        ]
        return "## User Personal Context & Facts\n" + "\n".join(lines)


__all__ = ["MicroFact", "UserMicroFactProfile"]
