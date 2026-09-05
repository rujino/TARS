"""Tier 1 Unit Tests: Background Knowledge Extraction Concurrency Throttling (ASY-06)
and Clean Architecture Layer Decoupling (ARC-01).

Verifies:
1. Module-level _EXTRACTION_SEMAPHORE bounds extraction concurrency to 10.
2. Concurrent stress test of 25 simultaneous extractions never exceeds 10 concurrent active workers.
3. Semaphore is safely released on regular exceptions and asyncio.CancelledError.
4. Early exit when parameters are empty does not acquire semaphore or allocate DB resources.
5. tars/orchestrator layer contains zero imports from tars.api (Clean Architecture adherence).
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tars.services.agent_chat import (
    execute_background_knowledge_extraction,
    get_extraction_semaphore,
)


@pytest.mark.asyncio
async def test_extraction_semaphore_initial_limit() -> None:
    """Verify that the extraction semaphore is initialized with bound 10."""
    semaphore = get_extraction_semaphore()
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == 10


@pytest.mark.asyncio
async def test_bounded_concurrency_stress() -> None:
    """Verify that 25 concurrent extractions never exceed 10 active tasks concurrently."""
    current_concurrency = 0
    max_observed_concurrency = 0
    lock = asyncio.Lock()
    total_completed = 0

    async def mock_extract_and_sync(*args: Any, **kwargs: Any) -> list[Any]:
        nonlocal current_concurrency, max_observed_concurrency, total_completed
        async with lock:
            current_concurrency += 1
            if current_concurrency > max_observed_concurrency:
                max_observed_concurrency = current_concurrency

        # Simulate heavy LLM extraction and DB indexing work
        await asyncio.sleep(0.04)

        async with lock:
            current_concurrency -= 1
            total_completed += 1

        return [MagicMock()]

    mock_db = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_db)
    mock_storage = MagicMock()
    mock_turns = [HumanMessage(content="Hello"), AIMessage(content="Greetings")]

    with (
        patch(
            "tars.services.agent_chat.get_session_factory",
            return_value=mock_session_factory,
        ),
        patch(
            "tars.services.agent_chat.SelfEvolvingKnowledgeWorker.extract_and_sync",
            side_effect=mock_extract_and_sync,
        ),
    ):
        tasks = [
            asyncio.create_task(
                execute_background_knowledge_extraction(
                    user_id=f"user_{i}",
                    conversation_turns=mock_turns,
                    storage=mock_storage,
                )
            )
            for i in range(25)
        ]
        await asyncio.gather(*tasks)

    # Concurrency must strictly never exceed 10
    assert max_observed_concurrency <= 10
    assert max_observed_concurrency >= 2
    assert total_completed == 25
    # All semaphore permits must be returned
    assert get_extraction_semaphore()._value == 10


@pytest.mark.asyncio
async def test_semaphore_released_on_general_exception() -> None:
    """Verify that if an unexpected exception occurs, the semaphore is cleanly released."""
    semaphore = get_extraction_semaphore()
    initial_value = semaphore._value

    mock_db = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_db)
    mock_storage = MagicMock()
    mock_turns = [HumanMessage(content="Query"), AIMessage(content="Answer")]

    with (
        patch(
            "tars.services.agent_chat.get_session_factory",
            return_value=mock_session_factory,
        ),
        patch(
            "tars.services.agent_chat.SelfEvolvingKnowledgeWorker.extract_and_sync",
            side_effect=RuntimeError("Simulated LLM network crash"),
        ),
    ):
        # execute_background_knowledge_extraction catches general exceptions and logs them
        await execute_background_knowledge_extraction(
            user_id="user_err",
            conversation_turns=mock_turns,
            storage=mock_storage,
        )

    # Semaphore value must be fully restored
    assert semaphore._value == initial_value


@pytest.mark.asyncio
async def test_semaphore_released_on_cancellation() -> None:
    """Verify that on asyncio.CancelledError, the error is re-raised and semaphore is released."""
    semaphore = get_extraction_semaphore()
    initial_value = semaphore._value

    mock_db = AsyncMock()
    mock_session_factory = MagicMock(return_value=mock_db)
    mock_storage = MagicMock()
    mock_turns = [HumanMessage(content="Query"), AIMessage(content="Answer")]

    with (
        patch(
            "tars.services.agent_chat.get_session_factory",
            return_value=mock_session_factory,
        ),
        patch(
            "tars.services.agent_chat.SelfEvolvingKnowledgeWorker.extract_and_sync",
            side_effect=asyncio.CancelledError(),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await execute_background_knowledge_extraction(
                user_id="user_cancel",
                conversation_turns=mock_turns,
                storage=mock_storage,
            )

    # Semaphore value must be fully restored
    assert semaphore._value == initial_value


@pytest.mark.asyncio
async def test_early_exit_no_semaphore_or_db_usage() -> None:
    """Verify that empty inputs exit immediately without touching semaphore or DB."""
    semaphore = get_extraction_semaphore()
    initial_value = semaphore._value

    mock_session_factory = MagicMock()
    mock_storage = MagicMock()

    with patch(
        "tars.services.agent_chat.get_session_factory",
        return_value=mock_session_factory,
    ):
        # Empty user_id
        await execute_background_knowledge_extraction(
            user_id="",
            conversation_turns=[HumanMessage(content="hi")],
            storage=mock_storage,
        )
        # Empty turns
        await execute_background_knowledge_extraction(
            user_id="user1",
            conversation_turns=[],
            storage=mock_storage,
        )

    # DB session factory should never have been called
    mock_session_factory.assert_not_called()
    assert semaphore._value == initial_value


def test_clean_architecture_zero_api_imports_in_orchestrator() -> None:
    """AST check to ensure tars/orchestrator has ZERO dependencies on tars.api (ARC-01)."""
    orchestrator_dir = Path(__file__).resolve().parents[2] / "tars" / "orchestrator"
    assert orchestrator_dir.is_dir()

    forbidden_prefix = "tars.api"
    violations: list[str] = []

    for py_file in orchestrator_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefix):
                        violations.append(
                            f"{py_file.name}:{node.lineno} imports '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(forbidden_prefix):
                    violations.append(
                        f"{py_file.name}:{node.lineno} from '{module}' import ..."
                    )

    assert not violations, f"Clean architecture violations found: {violations}"
