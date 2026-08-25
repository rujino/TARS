"""TARS Persona Package."""

from tars.persona.prompts import (
    TARSPersonaConfig,
    TARSPersonaManager,
    build_tars_system_prompt,
    generate_behavioral_instructions,
    render_knowledge_context,
)

__all__ = [
    "TARSPersonaConfig",
    "TARSPersonaManager",
    "build_tars_system_prompt",
    "generate_behavioral_instructions",
    "render_knowledge_context",
]
