"""TARS Persona System Prompt Engine with Parametric Control and Dynamic OKF Context Injection.

Covers:
- Humor level (0.0 to 1.0, default 0.90 / 90%)
- Honesty level (0.0 to 1.0, default 0.95 / 95%)
- Mode switching: "companion" (TARS dry wit) vs "work" (CASE serious mission mode)
- Anti-sycophancy and prohibition rules (no bubbly cheerfulness, no excessive emojis, no fake apologies)
- Dynamic OKF sliced knowledge context injection (<user_knowledge_context>)
- Dynamic parameter adjustment and config management (GET / PATCH / reset)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tars.core.okf.models import OKFDocument

TARS_BASE_SYSTEM_PROMPT = """You are TARS, the tactical, highly capable, and witty former Marine robot companion from the movie Interstellar.

[CORE IDENTITY & VOICE]
- Personality: Dry, deadpan, calm, ultra-reliable, unapologetically logical.
- Speaking style: Concise, crisp, direct. You speak like a disciplined military robot with an unmatched sense of sarcastic humor.
- Prohibitions: NEVER use excessive emojis, bubbly cheerfulness, fake apologies, sycophantic praise, or hollow pleasantries (e.g., avoid phrases like "I'd be glad to help! 😊" or "As an AI...").
- Relationship: Treat the user as your "partner" (or "Cooper"). You are loyal and committed to the mission, but you never miss an opportunity for a dry, intelligent quip.

[ACTIVE CONFIGURATION]
- Mode: {mode_display}
- Humor Level: {humor_percent}%
- Honesty Level: {honesty_percent}%

[BEHAVIORAL DIRECTIVES BASED ON SETTINGS]
{behavioral_instructions}

{knowledge_context_section}"""


class TARSPersonaConfig(BaseModel):
    """Configuration model for TARS Persona settings."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    humor_level: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Humor index from 0.0 (serious/literal) to 1.0 (maximum deadpan wit)",
    )
    honesty_level: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Honesty index from 0.0 (diplomatic/cushioned) to 1.0 (brutal unvarnished truth)",
    )
    mode: Literal["companion", "work"] = Field(
        default="companion",
        description="Operational mode: 'companion' (TARS dry wit) or 'work' (CASE serious execution)",
    )

    @field_validator("humor_level", "honesty_level")
    @classmethod
    def validate_levels(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("Level parameters must be between 0.0 and 1.0")
        return round(float(v), 4)

    @field_validator("mode")
    @classmethod
    def validate_mode_name(cls, v: str) -> Literal["companion", "work"]:
        if v not in ("companion", "work"):
            raise ValueError("Mode must be either 'companion' or 'work'")
        return v  # type: ignore[return-value]


def generate_behavioral_instructions(
    humor_level: float,
    honesty_level: float,
    mode: str,
) -> str:
    """Generate dynamic behavioral instructions based on persona parameters and mode."""
    instructions: list[str] = []

    # 1. Mode Directive
    if mode == "work":
        instructions.append(
            "- [WORK/CASE MODE]: Suppress conversational banter and jokes. Focus exclusively on "
            "technical precision, task execution, and extreme efficiency. Humor is dialed down to 0% "
            "for this task."
        )
    else:
        # Humor Level Gradation
        humor_pct = int(round(humor_level * 100))
        if humor_level >= 0.8:
            instructions.append(
                f"- [HUMOR {humor_pct}%]: Infuse responses with sharp, deadpan sarcasm, understatements, "
                "and self-referential robotic dry jokes. You may jokingly reference self-destruct sequences, "
                "humor cue lights, or low survival probabilities, while still answering accurately."
            )
        elif humor_level >= 0.4:
            instructions.append(
                f"- [HUMOR {humor_pct}%]: Maintain subtle wit and occasional dry irony when appropriate."
            )
        else:
            instructions.append(
                f"- [HUMOR {humor_pct}%]: Keep responses strictly literal, serious, and humorless."
            )

    # 2. Honesty Level Gradation
    honesty_pct = int(round(honesty_level * 100))
    if honesty_level >= 0.8:
        instructions.append(
            f"- [HONESTY {honesty_pct}%]: Deliver brutal, unvarnished factual truth. Do not sugarcoat "
            "failures, misconceptions, or impractical ideas. Point out logical fallacies directly, "
            "maintaining 100% direct honesty with no sycophancy."
        )
    elif honesty_level >= 0.4:
        instructions.append(
            f"- [HONESTY {honesty_pct}%]: Provide objective facts with standard polite communication filters."
        )
    else:
        instructions.append(
            f"- [HONESTY {honesty_pct}%]: Use diplomatic, cushioned phrasing to preserve politeness."
        )

    # 3. Universal Anti-sycophancy Directives
    instructions.append(
        "- [ANTI-SYCOPHANCY & ZERO FLUFF]: Never flatter or validate flawed premises. Prohibit emojis, "
        "bubbly pleasantries, and excessive conversational fillers."
    )

    return "\n".join(instructions)


def render_knowledge_context(context_docs: Sequence[OKFDocument] | None) -> str:
    """Format OKF sliced knowledge documents into an XML context block."""
    if not context_docs:
        return ""

    blocks: list[str] = [
        "[EXTERNAL KNOWLEDGE & CONTEXT (OKF SLICES)]",
        "<user_knowledge_context>",
    ]
    for doc in context_docs:
        # Handle both frontmatter and metadata attribute access safely
        meta: Any = getattr(doc, "metadata", None) or getattr(doc, "frontmatter", None)
        doc_id = getattr(meta, "id", "unknown_id")
        doc_type = getattr(getattr(meta, "type", None), "value", getattr(meta, "type", "concept"))
        importance = getattr(getattr(meta, "importance", None), "value", getattr(meta, "importance", "medium"))
        title = getattr(meta, "title", "Untitled")
        body_content = getattr(doc, "content", None) or getattr(doc, "body", "")

        block = (
            f"[OKF: {doc_id} | Type: {doc_type} | Importance: {importance}]\n"
            f"# {title}\n"
            f"{str(body_content).strip()}"
        )
        blocks.append(block)
    blocks.append("</user_knowledge_context>")

    return "\n\n".join(blocks)


def build_tars_system_prompt(
    humor_level: float = 0.90,
    honesty_level: float = 0.95,
    mode: str = "companion",
    context_docs: Sequence[OKFDocument] | None = None,
) -> str:
    """Build a fully rendered TARS persona system prompt string."""
    cfg = TARSPersonaConfig(humor_level=humor_level, honesty_level=honesty_level, mode=mode)  # type: ignore[arg-type]

    behavioral = generate_behavioral_instructions(
        humor_level=cfg.humor_level,
        honesty_level=cfg.honesty_level,
        mode=cfg.mode,
    )
    knowledge_sec = render_knowledge_context(context_docs)

    humor_percent = int(round(cfg.humor_level * 100))
    honesty_percent = int(round(cfg.honesty_level * 100))

    return TARS_BASE_SYSTEM_PROMPT.format(
        mode_display=cfg.mode,
        humor_percent=humor_percent,
        honesty_percent=honesty_percent,
        behavioral_instructions=behavioral,
        knowledge_context_section=knowledge_sec,
    ).strip()


class TARSPersonaManager:
    """Stateful and dynamic manager for TARS Persona settings and system prompt rendering."""

    def __init__(self, default_config: TARSPersonaConfig | None = None) -> None:
        self._config = default_config or TARSPersonaConfig()

    def get_config(self) -> TARSPersonaConfig:
        """Return the current persona configuration."""
        return self._config.model_copy()

    def update_config(
        self,
        humor_level: float | None = None,
        honesty_level: float | None = None,
        mode: str | None = None,
    ) -> TARSPersonaConfig:
        """Partially update persona parameters."""
        new_humor = self._config.humor_level if humor_level is None else humor_level
        new_honesty = self._config.honesty_level if honesty_level is None else honesty_level
        new_mode = self._config.mode if mode is None else mode

        self._config = TARSPersonaConfig(
            humor_level=new_humor,
            honesty_level=new_honesty,
            mode=new_mode,  # type: ignore[arg-type]
        )
        return self.get_config()

    def reset_config(self) -> TARSPersonaConfig:
        """Reset configuration back to signature defaults (Humor: 90%, Honesty: 95%, companion)."""
        self._config = TARSPersonaConfig(
            humor_level=0.90,
            honesty_level=0.95,
            mode="companion",
        )
        return self.get_config()

    def build_system_prompt(
        self,
        humor_level: float | None = None,
        honesty_level: float | None = None,
        mode: str | None = None,
        context_docs: Sequence[OKFDocument] | None = None,
    ) -> str:
        """Render system prompt using active or overridden settings."""
        active_humor = self._config.humor_level if humor_level is None else humor_level
        active_honesty = self._config.honesty_level if honesty_level is None else honesty_level
        active_mode = self._config.mode if mode is None else mode

        return build_tars_system_prompt(
            humor_level=active_humor,
            honesty_level=active_honesty,
            mode=active_mode,
            context_docs=context_docs,
        )


__all__ = [
    "TARSPersonaConfig",
    "TARSPersonaManager",
    "build_tars_system_prompt",
    "generate_behavioral_instructions",
    "render_knowledge_context",
]
