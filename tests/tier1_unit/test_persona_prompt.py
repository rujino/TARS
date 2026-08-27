"""Tier 1 Unit Tests: TARS Persona System Prompt Engine (F7).

Covers:
- Default parameters: Humor 90% (0.90), Honesty 95% (0.95), Mode 'companion'
- Behavioral directives generation across humor & honesty levels
- Mode switching: 'companion' (TARS dry wit) vs 'work' (CASE serious execution)
- Anti-sycophancy and prohibition rules (no bubbly emojis, no fake apologies)
- Dynamic OKF context slice injection into prompt
- Parameter boundary validation and error handling.
"""

from __future__ import annotations

import pytest

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFSource,
    OKFType,
)
from tars.persona.prompts import (
    TARSPersonaConfig,
    TARSPersonaManager,
)

# ============================================================================
# Helpers
# ============================================================================


def make_test_okf_doc(doc_id: str, title: str, content: str) -> OKFDocument:
    fm = OKFFrontmatter(
        id=doc_id,
        type=OKFType.RULE,
        title=title,
        source=OKFSource.SYSTEM,
    )
    return OKFDocument(metadata=fm, content=content)


# ============================================================================
# TARS Persona System Prompt Unit Tests (F7)
# ============================================================================


def test_persona_prompt_default_settings() -> None:
    """Verify default TARS prompt contains 90% humor, 95% honesty, and deadpan voice."""
    manager = TARSPersonaManager()
    prompt = manager.build_system_prompt(
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
    )

    assert "You are TARS" in prompt
    assert "Humor Level: 90%" in prompt
    assert "Honesty Level: 95%" in prompt
    assert "Mode: companion" in prompt
    assert "deadpan" in prompt.lower()
    # Anti-sycophancy rules
    assert "emojis" in prompt.lower()


def test_persona_prompt_work_mode_suppresses_humor() -> None:
    """Verify that mode='work' (CASE mode) suppresses humor and instructs task execution."""
    manager = TARSPersonaManager()
    prompt = manager.build_system_prompt(
        humor_level=0.90,
        honesty_level=0.95,
        mode="work",
    )

    assert "Mode: work" in prompt
    assert "CASE" in prompt or "WORK" in prompt
    assert "technical precision" in prompt.lower() or "efficiency" in prompt.lower()


def test_persona_prompt_humor_levels_gradation() -> None:
    """Verify humor level gradations (0%, 50%, 90%, 100%)."""
    manager = TARSPersonaManager()

    # 0% Humor (Literal / Serious)
    p_zero = manager.build_system_prompt(humor_level=0.0, honesty_level=0.95, mode="companion")
    assert "Humor Level: 0%" in p_zero

    # 50% Humor (Subtle Wit)
    p_mid = manager.build_system_prompt(humor_level=0.50, honesty_level=0.95, mode="companion")
    assert "Humor Level: 50%" in p_mid

    # 100% Humor (Maximum Sarcasm)
    p_max = manager.build_system_prompt(humor_level=1.00, honesty_level=0.95, mode="companion")
    assert "Humor Level: 100%" in p_max


def test_persona_prompt_honesty_levels_gradation() -> None:
    """Verify honesty level gradations (20% diplomatic, 95% brutal truth)."""
    manager = TARSPersonaManager()

    # 20% Honesty (Diplomatic)
    p_low = manager.build_system_prompt(humor_level=0.90, honesty_level=0.20, mode="companion")
    assert "Honesty Level: 20%" in p_low

    # 95% Honesty (Direct / Brutal Truth)
    p_high = manager.build_system_prompt(humor_level=0.90, honesty_level=0.95, mode="companion")
    assert "Honesty Level: 95%" in p_high
    assert "truth" in p_high.lower() or "direct" in p_high.lower()


def test_persona_prompt_anti_sycophancy_directives() -> None:
    """Verify strict prohibition of sycophancy, excessive emojis, and fake cheerfulness."""
    manager = TARSPersonaManager()
    prompt = manager.build_system_prompt()

    # Should forbid cheerful pleasantries
    lower_prompt = prompt.lower()
    assert "never" in lower_prompt or "prohibit" in lower_prompt or "avoid" in lower_prompt
    assert "pleasantries" in lower_prompt or "sycophant" in lower_prompt or "emoji" in lower_prompt


def test_persona_prompt_dynamic_okf_context_injection() -> None:
    """Verify that passed OKF context documents are injected into the system prompt."""
    doc1 = make_test_okf_doc("rule_nav", "Navigation Protocol", "Always calculate delta-v.")
    doc2 = make_test_okf_doc("pref_cue", "Cue Light", "Flash cue light when joking.")

    manager = TARSPersonaManager()
    prompt = manager.build_system_prompt(
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
        context_docs=[doc1, doc2],
    )

    assert "Navigation Protocol" in prompt
    assert "Always calculate delta-v." in prompt
    assert "Cue Light" in prompt
    assert "Flash cue light when joking." in prompt


def test_persona_config_boundary_validation() -> None:
    """Verify out-of-range humor or honesty values raise validation errors in TARSPersonaConfig."""
    with pytest.raises((ValueError, Exception)):
        TARSPersonaConfig(humor_level=1.5, honesty_level=0.95, mode="companion")

    with pytest.raises((ValueError, Exception)):
        TARSPersonaConfig(humor_level=-0.1, honesty_level=0.95, mode="companion")

    with pytest.raises((ValueError, Exception)):
        TARSPersonaConfig(humor_level=0.90, honesty_level=0.95, mode="invalid_mode")  # type: ignore[arg-type]
