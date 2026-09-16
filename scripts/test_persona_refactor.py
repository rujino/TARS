"""Test suite for TARS character refactoring (Thoughtful Adaptive Reflective System)."""

import pytest
from pydantic import ValidationError

from tars.domains.chat.services.greeting import ProactiveGreetingService
from tars.domains.persona.prompts import (
    TARSPersonaConfig,
    build_greeting_prompt,
    build_tars_system_prompt,
)
from tars.domains.persona.schemas import TARSConfigResponse, TARSConfigUpdateRequest
from tars.engine.orchestrator.nodes.prompt import prompt_node
from tars.engine.orchestrator.state import TARSState


def test_tars_persona_config_modes():
    """Verify TARSPersonaConfig supports attend and task modes and normalizes legacy modes."""
    cfg_default = TARSPersonaConfig()
    assert cfg_default.mode == "attend"
    assert cfg_default.normalized_mode == "attend"

    cfg_task = TARSPersonaConfig(mode="task")
    assert cfg_task.mode == "task"
    assert cfg_task.normalized_mode == "task"

    # Legacy mapping
    cfg_comp = TARSPersonaConfig(mode="companion")
    assert cfg_comp.normalized_mode == "attend"

    cfg_work = TARSPersonaConfig(mode="work")
    assert cfg_work.normalized_mode == "task"

    # Invalid mode raises error
    with pytest.raises(ValidationError):
        TARSPersonaConfig(mode="invalid_mode")  # type: ignore[arg-type]


def test_tars_system_prompt_identity():
    """Verify system prompt uses Thoughtful Adaptive Reflective System and addresses user as 주인님."""
    prompt = build_tars_system_prompt(mode="attend")

    # Positive assertions
    assert "Thoughtful Adaptive Reflective System" in prompt
    assert "주인님" in prompt
    assert "[ATTEND MODE]" in prompt

    # Negative assertions (Interstellar & humor/honesty tropes removed)
    assert "Humor Level" not in prompt
    assert "Honesty Level" not in prompt
    assert "former Marine robot" not in prompt
    assert "Cooper" not in prompt
    assert "sarcastic humor" not in prompt


def test_tars_greeting_prompt():
    """Verify proactive greeting prompt addresses user as 주인님 and has no humor/honesty."""
    prompt = build_greeting_prompt(
        mode="attend",
        time_of_day_str="오후",
        current_time_str="14:00",
        idle_duration_str="2시간 전",
        last_session_topic="아키텍처 설계",
    )
    assert "주인님" in prompt
    assert "Humor:" not in prompt
    assert "Honesty:" not in prompt
    assert "파트너" not in prompt


def test_tars_fallback_greeting():
    """Verify deterministic fallback greetings address user respectfully as 주인님."""
    service = ProactiveGreetingService(
        db_session=None,  # type: ignore[arg-type]
        storage_manager=None,  # type: ignore[arg-type]
        llm_adapter=None,
    )

    # Standard daytime greeting
    day_greeting = service._generate_fallback_greeting(
        mode="attend",
        time_period="오후",
        hour=14,
        idle_seconds=600,
    )
    assert "주인님" in day_greeting
    assert "유머 지수" not in day_greeting
    assert "정직성" not in day_greeting

    # Late night greeting
    night_greeting = service._generate_fallback_greeting(
        mode="attend",
        time_period="새벽",
        hour=2,
        idle_seconds=600,
    )
    assert "주인님" in night_greeting
    assert "생체 리듬" not in night_greeting

    # Long absence greeting
    absence_greeting = service._generate_fallback_greeting(
        mode="attend",
        time_period="오전",
        hour=10,
        idle_seconds=86400 * 3,
    )
    assert "주인님" in absence_greeting
    assert "행성 탐사" not in absence_greeting

    # Task mode greeting
    task_greeting = service._generate_fallback_greeting(
        mode="task",
        time_period="오후",
        hour=15,
        idle_seconds=100,
    )
    assert "주인님" in task_greeting
    assert "작업 모드" in task_greeting


def test_tars_schemas_compatibility():
    """Verify TARSConfigResponse and TARSConfigUpdateRequest work cleanly without humor/honesty."""
    # Response model validation
    resp = TARSConfigResponse(mode="attend")
    assert resp.mode == "attend"
    assert "humor_level" not in resp.model_dump()
    assert "honesty_level" not in resp.model_dump()

    # Update request model validation (ignoring legacy humor/honesty gracefully)
    update = TARSConfigUpdateRequest.model_validate(
        {"mode": "task", "humor_level": 0.85, "honesty_level": 0.9}
    )
    assert update.mode == "task"

    # Legacy mode mapping
    update_legacy = TARSConfigUpdateRequest.model_validate({"mode": "companion"})
    assert update_legacy.mode == "attend"


@pytest.mark.asyncio
async def test_prompt_node_execution():
    """Verify orchestrator prompt_node runs cleanly with updated state."""
    state: TARSState = {
        "user_id": "test_user",
        "session_id": "sess_001",
        "mode": "attend",
        "relevant_wikis": [],
    }
    result = await prompt_node(state)
    assert "system_prompt" in result
    assert "Thoughtful Adaptive Reflective System" in result["system_prompt"]
    assert "주인님" in result["system_prompt"]
    assert "Humor Level" not in result["system_prompt"]
