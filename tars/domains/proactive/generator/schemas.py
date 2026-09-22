"""Schemas for proactive message synthesis and generator inputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tars.domains.knowledge.spec.schemas import OKFImportance
from tars.domains.proactive.schemas import ScheduleType


class GeneratorInput(BaseModel):
    """Contextual input parameters for ProactiveMessageGenerator."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    persona_id: str
    schedule_type: ScheduleType
    okf_document_summary: str | None = None
    okf_title: str | None = None
    okf_importance: OKFImportance | None = None
    last_conversation_fragment: str | None = None
    temporal_context: str
    elapsed_days: float | None = None
    review_cycle_days: int | None = None
    threshold_score: float = 0.0


class GeneratorOutput(BaseModel):
    """Synthesized proactive utterance result."""

    model_config = ConfigDict(extra="ignore")

    content: str
    persona_id: str
    schedule_type: ScheduleType


__all__ = ["GeneratorInput", "GeneratorOutput"]
