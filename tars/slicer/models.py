"""Models, protocols, and configuration schemas for TARS Dynamic Slicer Engine."""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from tars.core.okf.models import OKFDocument, OKFImportance, OKFType


class SlicerProfile(str, Enum):
    """Dynamic slicing context profile."""

    CHAT = "chat"
    GREETING = "greeting"
    TASK = "task"


@runtime_checkable
class ITokenCounter(Protocol):
    """Protocol defining token counting contract."""

    def count_tokens(self, text: str) -> int:
        """Count or estimate the number of tokens in the provided text string."""
        ...


class HeuristicTokenCounter:
    """High-performance heuristic token counter optimized for CJK and ASCII text.

    Estimation rule:
    - ASCII / alphanumeric / symbols: ~4 chars per token.
    - CJK / Hangul / East Asian wide chars: ~1.5 chars per token.
    """

    __slots__ = ()

    def count_tokens(self, text: str) -> int:
        """Calculate estimated token count for text."""
        if not text:
            return 0

        cjk_count = 0
        ascii_count = 0

        for char in text:
            code = ord(char)
            # Hangul Jamo, Compatibility Jamo, Hangul Syllables, CJK Ideographs
            if (
                0x1100 <= code <= 0x11FF
                or 0x3130 <= code <= 0x318F
                or 0xAC00 <= code <= 0xD7AF
                or 0x2E80 <= code <= 0x9FFF
                or 0xF900 <= code <= 0xFAFF
            ):
                cjk_count += 1
            else:
                ascii_count += 1

        estimated = (ascii_count / 4.0) + (cjk_count / 1.5)
        return max(1, math.ceil(estimated))


class SlicerWeights(BaseModel):
    """Configuration weights for multi-factor scoring formula."""

    model_config = ConfigDict(frozen=True)

    weight_importance: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_match: float = Field(default=0.40, ge=0.0, le=1.0)
    weight_type: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_recency: float = Field(default=0.10, ge=0.0, le=1.0)
    weight_relation: float = Field(default=0.0, ge=0.0, le=1.0)


IMPORTANCE_SCORE_MAP: Mapping[OKFImportance, float] = {
    OKFImportance.CRITICAL: 1.00,
    OKFImportance.HIGH: 0.75,
    OKFImportance.MEDIUM: 0.50,
    OKFImportance.LOW: 0.20,
}

TYPE_SCORE_MAP: Mapping[OKFType, float] = {
    OKFType.RULE: 1.00,
    OKFType.PREFERENCE: 0.90,
    OKFType.PROCEDURE: 0.70,
    OKFType.ENTITY: 0.50,
    OKFType.CONCEPT: 0.40,
}

CHAT_TYPE_MAP: Mapping[OKFType, float] = {
    OKFType.RULE: 1.00,
    OKFType.PREFERENCE: 0.90,
    OKFType.PROCEDURE: 0.70,
    OKFType.ENTITY: 0.50,
    OKFType.CONCEPT: 0.40,
}

GREETING_TYPE_MAP: Mapping[OKFType, float] = {
    OKFType.PREFERENCE: 1.00,
    OKFType.RULE: 0.90,
    OKFType.ENTITY: 0.60,
    OKFType.CONCEPT: 0.30,
    OKFType.PROCEDURE: 0.20,
}

TASK_TYPE_MAP: Mapping[OKFType, float] = {
    OKFType.PROCEDURE: 1.00,
    OKFType.RULE: 0.90,
    OKFType.ENTITY: 0.70,
    OKFType.CONCEPT: 0.50,
    OKFType.PREFERENCE: 0.30,
}

PROFILE_TYPE_MAPS: Mapping[SlicerProfile, Mapping[OKFType, float]] = {
    SlicerProfile.CHAT: CHAT_TYPE_MAP,
    SlicerProfile.GREETING: GREETING_TYPE_MAP,
    SlicerProfile.TASK: TASK_TYPE_MAP,
}

PROFILE_WEIGHTS: Mapping[SlicerProfile, SlicerWeights] = {
    SlicerProfile.CHAT: SlicerWeights(
        weight_importance=0.25,
        weight_match=0.40,
        weight_type=0.25,
        weight_recency=0.10,
    ),
    SlicerProfile.GREETING: SlicerWeights(
        weight_importance=0.20,
        weight_match=0.20,
        weight_type=0.40,
        weight_recency=0.20,
    ),
    SlicerProfile.TASK: SlicerWeights(
        weight_importance=0.30,
        weight_match=0.35,
        weight_type=0.25,
        weight_recency=0.10,
    ),
}


class SlicedContextResult(BaseModel):
    """Result structure containing sliced documents and prompt context metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    selected_documents: list[OKFDocument] = Field(default_factory=list)
    total_estimated_tokens: int = Field(default=0)
    formatted_context: str = Field(default="")
    scores: dict[str, float] = Field(default_factory=dict)

    @property
    def documents(self) -> list[OKFDocument]:
        """Alias for selected_documents."""
        return self.selected_documents

    @property
    def total_tokens(self) -> int:
        """Alias for total_estimated_tokens."""
        return self.total_estimated_tokens


# Alias for backward and blueprint compatibility
SlicedKnowledgeResult = SlicedContextResult


__all__ = [
    "CHAT_TYPE_MAP",
    "GREETING_TYPE_MAP",
    "IMPORTANCE_SCORE_MAP",
    "ITokenCounter",
    "PROFILE_TYPE_MAPS",
    "PROFILE_WEIGHTS",
    "HeuristicTokenCounter",
    "SlicedContextResult",
    "SlicedKnowledgeResult",
    "SlicerProfile",
    "SlicerWeights",
    "TASK_TYPE_MAP",
    "TYPE_SCORE_MAP",
]
