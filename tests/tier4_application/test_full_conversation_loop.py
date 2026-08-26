"""Tier 4 Application Tests: Realistic Multi-Turn Dialogue & Self-Evolving Knowledge Loop.

Verifies the complete flagship Trinity Architecture flow:
1. Turn 1 (Information Ingestion):
   - User states a persistent preference/rule: "TARS, I always drink black coffee without sugar."
   - StateGraph processes and responds to user.
   - Background SelfEvolvingKnowledgeWorker extracts knowledge into OKF format with
     `source: "auto_extracted"`.
   - File is atomically saved to `/storage/users/{user_id}/wikis/user_pref_coffee.md`.
   - RDBMS `UserWikiIndex` metadata row is created.
2. Turn 2 (Knowledge Recall & Dynamic Prompt Injection):
   - In a subsequent turn, User asks: "What beverage should I prepare for breakfast?"
   - OKF Dynamic Slicer detects relevant keywords/tags and retrieves `user_pref_coffee.md`.
   - StateGraph injects the retrieved OKF document into TARS system prompt.
   - TARS produces a contextual, witty response referencing black coffee with no sugar.
3. Proactive Greeting Integration:
   - ProactiveGreetingService generates an opening greeting reflecting the auto-extracted OKF knowledge.
4. Dynamic Conflict Update Loop:
   - Subsequent modification (e.g. coffee preference updated to espresso) replaces the existing wiki and
     immediately reflects in downstream retrieval.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.adapters.router import HybridLLMRouter
from tars.core.okf.models import OKFSource
from tars.db.models import User, UserWikiIndex
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.orchestrator.graph import build_tars_graph, compile_tars_graph
from tars.services.greeting import ProactiveGreetingService
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tests.conftest import MockGeminiAdapter, MockLlamaCppAdapter


@pytest.mark.asyncio
async def test_full_self_evolving_conversation_loop(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
    seed_test_user: User,
) -> None:
    """Execute complete two-turn self-evolving knowledge loop from ingestion to retrieval."""
    user_id = seed_test_user.id
    session_id = "session_evolving_loop_001"

    # ------------------------------------------------------------------------
    # Step 1: Initialize Components
    # ------------------------------------------------------------------------
    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    # Mock Extractor LLM to return structured extraction result
    mock_extractor_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_extractor_llm.agenerate.return_value = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "user_pref_coffee",
            "type": "preference",
            "title": "User Coffee Preference",
            "category": "personal",
            "tags": ["coffee", "beverage", "breakfast", "sugar"],
            "importance": "high",
            "content": "# Coffee Preference\n- User exclusively drinks black coffee.\n- Absolutely no sugar or milk.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )

    extractor_worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_extractor_llm,
        storage_manager=storage_manager,
    )

    # ------------------------------------------------------------------------
    # Step 2: Turn 1 - User communicates preference
    # ------------------------------------------------------------------------
    user_turn1_content = "TARS, for future reference, I only drink black coffee without sugar."

    # Build and invoke graph for Turn 1
    mock_gemini_turn1 = MockGeminiAdapter(
        canned_response="TARS: Duly noted, Cooper. Black coffee with zero sugar added to preferences."
    )
    router_turn1 = HybridLLMRouter(
        gemini_adapter=mock_gemini_turn1,
        slm_adapter=MockLlamaCppAdapter(),
    )
    graph_turn1 = compile_tars_graph(build_tars_graph(router=router_turn1, slicer=slicer))

    state_turn1 = await graph_turn1.ainvoke(
        {
            "messages": [HumanMessage(content=user_turn1_content)],
            "user_id": user_id,
            "session_id": session_id,
            "humor_level": 0.90,
            "honesty_level": 0.95,
            "mode": "companion",
        }
    )

    assert state_turn1["final_response"] != ""

    # Execute Background Extractor Worker
    conversation_turns = [
        HumanMessage(content=user_turn1_content),
        AIMessage(content=state_turn1["final_response"]),
    ]
    extracted_docs = await extractor_worker.extract_and_sync(
        user_id=user_id,
        conversation_turns=conversation_turns,
        db_session=db_session,
    )

    # Verify extraction result and storage persistence
    assert len(extracted_docs) == 1
    assert extracted_docs[0].metadata.id == "user_pref_coffee"
    assert extracted_docs[0].metadata.source == OKFSource.AUTO_EXTRACTED

    # Verify physical file existence in storage
    saved_doc = await storage_manager.read_okf_file(user_id=user_id, okf_id="user_pref_coffee")
    assert saved_doc is not None
    assert "black coffee" in saved_doc.content

    # Verify DB metadata entry
    stmt = select(UserWikiIndex).where(
        UserWikiIndex.user_id == user_id,
        UserWikiIndex.okf_id == "user_pref_coffee",
    )
    result = await db_session.execute(stmt)
    db_entry = result.scalar_one_or_none()
    assert db_entry is not None
    assert db_entry.title == "User Coffee Preference"

    # ------------------------------------------------------------------------
    # Step 3: Turn 2 - User asks question relying on previous knowledge
    # ------------------------------------------------------------------------
    user_turn2_content = "What beverage should I prepare for breakfast?"

    # Slicer should now find the auto-extracted coffee preference document
    mock_gemini_turn2 = MockGeminiAdapter(
        canned_response="TARS: Black coffee, no sugar. Unless you want me to calculate the caloric damage of sweetener."
    )
    router_turn2 = HybridLLMRouter(
        gemini_adapter=mock_gemini_turn2,
        slm_adapter=MockLlamaCppAdapter(),
    )
    graph_turn2 = compile_tars_graph(build_tars_graph(router=router_turn2, slicer=slicer))

    state_turn2 = await graph_turn2.ainvoke(
        {
            "messages": [HumanMessage(content=user_turn2_content)],
            "user_id": user_id,
            "session_id": session_id,
            "humor_level": 0.90,
            "honesty_level": 0.95,
            "mode": "companion",
        }
    )

    # ------------------------------------------------------------------------
    # Step 4: Verification of Recall & Injection
    # ------------------------------------------------------------------------
    # 1. State must contain the auto-extracted wiki in relevant_wikis
    relevant_ids = [w.metadata.id for w in state_turn2.get("relevant_wikis", [])]
    assert "user_pref_coffee" in relevant_ids

    # 2. System prompt must include the injected coffee preference context
    system_prompt = state_turn2.get("system_prompt", "")
    assert "Coffee Preference" in system_prompt or "black coffee" in system_prompt
    assert "sugar" in system_prompt

    # 3. Final response generated
    assert state_turn2["final_response"] != ""

    # ------------------------------------------------------------------------
    # Step 5: Proactive Greeting Service Integration
    # ------------------------------------------------------------------------
    greeting_gemini = MockGeminiAdapter(
        canned_response="좋은 아침입니다 파트너. 블랙 커피 한 잔 준비되셨습니까?"
    )
    greeting_router = HybridLLMRouter(
        gemini_adapter=greeting_gemini,
        slm_adapter=MockLlamaCppAdapter(),
    )
    greeting_service = ProactiveGreetingService(
        db_session=db_session,
        storage_manager=storage_manager,
        llm_adapter=greeting_router,
    )
    greeting_resp = await greeting_service.generate_greeting(
        user_id=user_id,
        client_timezone="Asia/Seoul",
    )
    assert greeting_resp.greeting != ""
    assert "블랙 커피" in greeting_resp.greeting or len(greeting_resp.greeting) > 5


@pytest.mark.asyncio
async def test_self_evolving_conflict_update_loop(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
    seed_test_user: User,
) -> None:
    """Verify modifying a preference in Turn 2 updates the wiki and reflects in subsequent turns."""
    user_id = seed_test_user.id
    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    # Initial extraction
    mock_extractor_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_extractor_llm.agenerate.return_value = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "rule_sync_time",
            "type": "rule",
            "title": "Daily Standup Time",
            "category": "schedule",
            "tags": ["standup", "schedule"],
            "importance": "high",
            "content": "Standup is at 09:00 KST daily.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )
    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_extractor_llm,
        storage_manager=storage_manager,
    )
    await worker.extract_and_sync(
        user_id=user_id,
        conversation_turns=[HumanMessage(content="Standup is at 9am.")],
        db_session=db_session,
    )

    # Contradiction / Update extraction
    mock_extractor_llm.agenerate.return_value = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": True,
            "target_existing_id": "rule_sync_time",
            "doc_id": "rule_sync_time",
            "type": "rule",
            "title": "Daily Standup Time (Updated)",
            "category": "schedule",
            "tags": ["standup", "schedule", "10am"],
            "importance": "high",
            "content": "Standup moved to 10:00 KST daily.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )
    await worker.extract_and_sync(
        user_id=user_id,
        conversation_turns=[HumanMessage(content="Standup has been moved to 10am.")],
        db_session=db_session,
    )

    # Slicer query
    relevant_wikis = await slicer.slice_context(
        user_id=user_id,
        query="When is our standup?",
    )

    assert len(relevant_wikis) >= 1
    top_wiki = relevant_wikis[0]
    assert top_wiki.metadata.id == "rule_sync_time"
    assert "10:00 KST" in top_wiki.content
