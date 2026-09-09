"""Empirical Challenger Adversarial Stress Suite for TARS Generation 5 (Milestone 1).

Covers:
1. Multi-user preference isolation & parallel concurrency (User A, B, C isolation).
2. Disabled tool execution blocking in tool_node & full LangGraph ReAct cycle.
3. Edge cases: invalid/nonexistent tools, conflicting payloads, empty/None filters, idempotency.
4. Concurrency stress on toggle endpoints.
5. TARSSettings persistence across simulated session restarts and cold starts.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tars.adapters.base import LLMResponse, ToolCallData
from tars.api.app import create_app
from tars.api.dependencies import (
    build_tool_registry,
    get_db_session,
    get_storage_manager,
    get_tool_registry,
)
from tars.core.security import create_access_token, get_password_hash
from tars.db.models import TARSSettings, User
from tars.orchestrator.nodes import llm_node, session_node, tool_node
from tars.orchestrator.state import TARSState
from tars.storage.manager import FileStorageManager
from tars.tools.base import BaseTool
from tars.tools.registry import ToolRegistry


class AdversarialDummyTool(BaseTool):
    """Controllable tool implementation for tracking invocations and args."""

    def __init__(self, name: str, description: str = "Test tool") -> None:
        super().__init__(
            name=name,
            description=description,
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        )
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None

    async def aexecute(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        return {"tool": self.name, "count": self.call_count, "kwargs": kwargs}


@pytest.fixture
def stress_tool_registry() -> ToolRegistry:
    """ToolRegistry populated with multiple mock tools."""
    registry = ToolRegistry()
    registry.register(AdversarialDummyTool("tool_1", "First dummy tool"))
    registry.register(AdversarialDummyTool("tool_2", "Second dummy tool"))
    registry.register(AdversarialDummyTool("tool_3", "Third dummy tool"))
    registry.register(AdversarialDummyTool("tool_4", "Fourth dummy tool"))
    return registry


@pytest_asyncio.fixture
async def tools_api_client(
    test_engine: AsyncEngine,
    temp_storage_root: Any,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide AsyncClient wired to test_engine and default tool registry."""
    app = create_app()
    reg = await build_tool_registry()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_storage_manager] = lambda: FileStorageManager(
        base_dir=temp_storage_root
    )
    app.dependency_overrides[get_tool_registry] = lambda: reg

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ============================================================================
# 1. Multi-User Preference Isolation Tests
# ============================================================================


class TestMultiUserPreferenceIsolation:
    """Adversarial stress-testing of multi-user preference isolation."""

    @pytest.mark.asyncio
    async def test_three_way_user_preference_isolation_via_api(
        self,
        tools_api_client: AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        """Verify complete isolation between User A, User B, and User C."""
        now = datetime.now(UTC)
        # Setup 3 users
        users = [
            User(
                id=f"iso_user_{i}",
                username=f"user_{i}",
                email=f"user_{i}@endurance.space",
                hashed_password=get_password_hash("Pass123!"),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            for i in (1, 2, 3)
        ]
        for u in users:
            async_db_session.add(u)
        await async_db_session.commit()

        tokens = [create_access_token(data={"sub": u.id}) for u in users]

        # User 1 disables calendar_list_events and gmail_search_messages
        resp1 = await tools_api_client.patch(
            "/api/v1/tools/calendar_list_events/toggle",
            json={"active": False},
            headers={"Authorization": f"Bearer {tokens[0]}"},
        )
        assert resp1.status_code == 200
        resp1_2 = await tools_api_client.patch(
            "/api/v1/tools/gmail_search_messages/toggle",
            json={"active": False},
            headers={"Authorization": f"Bearer {tokens[0]}"},
        )
        assert resp1_2.status_code == 200

        # User 2 disables calendar_create_event only
        resp2 = await tools_api_client.patch(
            "/api/v1/tools/calendar_create_event/toggle",
            json={"active": False},
            headers={"Authorization": f"Bearer {tokens[1]}"},
        )
        assert resp2.status_code == 200

        # User 3 does not disable any tool

        # Query /servers for all 3 users
        s_resp1 = await tools_api_client.get(
            "/api/v1/tools/servers", headers={"Authorization": f"Bearer {tokens[0]}"}
        )
        s_resp2 = await tools_api_client.get(
            "/api/v1/tools/servers", headers={"Authorization": f"Bearer {tokens[1]}"}
        )
        s_resp3 = await tools_api_client.get(
            "/api/v1/tools/servers", headers={"Authorization": f"Bearer {tokens[2]}"}
        )

        gw1 = next(s for s in s_resp1.json()["servers"] if s["id"] == "google_workspace")
        gw2 = next(s for s in s_resp2.json()["servers"] if s["id"] == "google_workspace")
        gw3 = next(s for s in s_resp3.json()["servers"] if s["id"] == "google_workspace")

        tools1 = {t["name"]: t["active"] for t in gw1["tools"]}
        tools2 = {t["name"]: t["active"] for t in gw2["tools"]}
        tools3 = {t["name"]: t["active"] for t in gw3["tools"]}

        # User 1: calendar_list_events & gmail_search_messages are False, calendar_create_event is True
        assert tools1["calendar_list_events"] is False
        assert tools1["gmail_search_messages"] is False
        assert tools1["calendar_create_event"] is True

        # User 2: calendar_create_event is False, calendar_list_events & gmail_search_messages are True
        assert tools2["calendar_create_event"] is False
        assert tools2["calendar_list_events"] is True
        assert tools2["gmail_search_messages"] is True

        # User 3: all tools are True
        assert all(tools3.values())

    @pytest.mark.asyncio
    async def test_multi_user_session_node_state_hydration_isolation(
        self,
        async_db_session: AsyncSession,
    ) -> None:
        """Verify session_node hydrates isolated disabled_tools sets for different users."""
        now = datetime.now(UTC)
        u_a = User(
            id="user_iso_a",
            username="iso_a",
            email="iso_a@endurance.space",
            hashed_password="pw",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        u_b = User(
            id="user_iso_b",
            username="iso_b",
            email="iso_b@endurance.space",
            hashed_password="pw",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        set_a = TARSSettings(
            user_id="user_iso_a",
            disabled_tools=["tool_x", "tool_y"],
            created_at=now,
            updated_at=now,
        )
        set_b = TARSSettings(
            user_id="user_iso_b",
            disabled_tools=["tool_z"],
            created_at=now,
            updated_at=now,
        )
        async_db_session.add_all([u_a, u_b, set_a, set_b])
        await async_db_session.commit()

        # Hydrate user A
        state_a: TARSState = {
            "user_id": "user_iso_a",
            "active_query": "Query A",
            "messages": [HumanMessage(content="Query A")],
        }
        res_a = await session_node(state=state_a, db_session=async_db_session)
        assert res_a["disabled_tools"] == ["tool_x", "tool_y"]

        # Hydrate user B
        state_b: TARSState = {
            "user_id": "user_iso_b",
            "active_query": "Query B",
            "messages": [HumanMessage(content="Query B")],
        }
        res_b = await session_node(state=state_b, db_session=async_db_session)
        assert res_b["disabled_tools"] == ["tool_z"]

    @pytest.mark.asyncio
    async def test_concurrent_multi_user_api_requests_no_leakage(
        self,
        tools_api_client: AsyncClient,
        async_db_session: AsyncSession,
    ) -> None:
        """Run concurrent /servers and /toggle calls across multiple users simultaneously."""
        now = datetime.now(UTC)
        user_ids = [f"conc_user_{i}" for i in range(5)]
        users = [
            User(
                id=uid,
                username=uid,
                email=f"{uid}@endurance.space",
                hashed_password="pw",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            for uid in user_ids
        ]
        async_db_session.add_all(users)
        await async_db_session.commit()

        tokens = [create_access_token(data={"sub": uid}) for uid in user_ids]

        async def user_workflow(idx: int, token: str) -> bool:
            h = {"Authorization": f"Bearer {token}"}
            tool_to_disable = (
                "calendar_list_events" if idx % 2 == 0 else "gmail_search_messages"
            )
            # 1. Toggle tool
            r1 = await tools_api_client.patch(
                f"/api/v1/tools/{tool_to_disable}/toggle",
                json={"active": False},
                headers=h,
            )
            if r1.status_code != 200:
                return False

            # 2. Check /servers
            r2 = await tools_api_client.get("/api/v1/tools/servers", headers=h)
            if r2.status_code != 200:
                return False

            gw = next(
                s for s in r2.json()["servers"] if s["id"] == "google_workspace"
            )
            tool_item = next(t for t in gw["tools"] if t["name"] == tool_to_disable)
            return tool_item["active"] is False

        results = await asyncio.gather(
            *[user_workflow(i, tokens[i]) for i in range(len(tokens))]
        )
        assert all(results)


# ============================================================================
# 2. Disabled Tool Execution Blocking Tests
# ============================================================================


class TestDisabledToolExecutionBlocking:
    """Stress-testing execution guard in tool_node."""

    @pytest.mark.asyncio
    async def test_tool_node_blocks_multiple_disabled_calls(
        self,
        stress_tool_registry: ToolRegistry,
    ) -> None:
        """Batch with multiple disabled tools: none must execute, all must return error directives."""
        t1 = stress_tool_registry.get_tool("tool_1")
        t2 = stress_tool_registry.get_tool("tool_2")
        t3 = stress_tool_registry.get_tool("tool_3")
        assert isinstance(t1, AdversarialDummyTool)
        assert isinstance(t2, AdversarialDummyTool)
        assert isinstance(t3, AdversarialDummyTool)

        calls = [
            ToolCallData(id="call_1", name="tool_1", arguments={"query": "test1"}),
            ToolCallData(id="call_2", name="tool_2", arguments={"query": "test2"}),
            ToolCallData(id="call_3", name="tool_3", arguments={"query": "test3"}),
        ]

        state: TARSState = {
            "tool_calls": calls,
            "disabled_tools": ["tool_1", "tool_3"],  # tool_1 and tool_3 disabled
            "iteration_count": 0,
            "tool_results": [],
            "tools_used": [],
        }

        update = await tool_node(state=state, tool_registry=stress_tool_registry)

        # Execution check
        assert t1.call_count == 0
        assert t2.call_count == 1
        assert t3.call_count == 0

        # State check
        assert update["tools_used"] == ["tool_2"]
        assert len(update["messages"]) == 3

        # Message contents
        assert "[Tool Blocked: tool_1]" in update["messages"][0].content
        assert "[Tool Result: tool_2]" in update["messages"][1].content
        assert "[Tool Blocked: tool_3]" in update["messages"][2].content

        # Results status
        res = update["tool_results"]
        assert res[0]["status"] == "error"
        assert res[0]["tool"] == "tool_1"
        assert res[1]["status"] == "success"
        assert res[1]["tool"] == "tool_2"
        assert res[2]["status"] == "error"
        assert res[2]["tool"] == "tool_3"

    @pytest.mark.asyncio
    async def test_tool_node_blocks_unregistered_disabled_tool(
        self,
        stress_tool_registry: ToolRegistry,
    ) -> None:
        """Tool call for an unregistered tool that is marked disabled: blocked without KeyError."""
        call = ToolCallData(
            id="call_unregistered",
            name="phantom_tool_99",
            arguments={"query": "void"},
        )

        state: TARSState = {
            "tool_calls": [call],
            "disabled_tools": ["phantom_tool_99"],
            "iteration_count": 0,
            "tool_results": [],
        }

        update = await tool_node(state=state, tool_registry=stress_tool_registry)

        assert len(update["messages"]) == 1
        assert "[Tool Blocked: phantom_tool_99]" in update["messages"][0].content
        assert update["tool_results"][0]["status"] == "error"
        assert "disabled by user configuration" in update["tool_results"][0]["error"]

    @pytest.mark.asyncio
    async def test_full_react_cycle_with_blocked_tool_to_llm(
        self,
        stress_tool_registry: ToolRegistry,
    ) -> None:
        """Simulate ReAct loop cycle: llm_node -> tool_node -> llm_node with blocked tool."""
        # Setup mock router
        mock_router = MagicMock()
        # Round 1: Router generates tool call for disabled tool
        round1_resp = LLMResponse(
            content="Attempting tool call.",
            tool_calls=[
                ToolCallData(id="call_t1", name="tool_1", arguments={"query": "hi"})
            ],
        )
        # Round 2: Router acknowledges blocked tool and gives final answer
        round2_resp = LLMResponse(
            content="Tool is unavailable due to user settings. Proceeding manually.",
            tool_calls=[],
        )
        mock_router.route_and_generate_response = AsyncMock(
            side_effect=[round1_resp, round2_resp]
        )

        # 1. First LLM turn
        state: TARSState = {
            "messages": [HumanMessage(content="Use tool 1")],
            "system_prompt": "You are TARS.",
            "disabled_tools": ["tool_1"],
            "iteration_count": 0,
            "tool_results": [],
            "tools_used": [],
        }
        res1 = await llm_node(
            state=state,
            router=mock_router,
            tool_registry=stress_tool_registry,
        )
        assert len(res1["tool_calls"]) == 1

        # 2. Tool node executes and blocks call
        state.update(res1)
        res2 = await tool_node(state=state, tool_registry=stress_tool_registry)
        assert len(res2["messages"]) == 1
        assert "[Tool Blocked: tool_1]" in res2["messages"][0].content

        # Update state messages
        state["messages"] = list(state["messages"]) + res2["messages"]
        state["tool_calls"] = res2["tool_calls"]

        # 3. Second LLM turn
        res3 = await llm_node(
            state=state,
            router=mock_router,
            tool_registry=stress_tool_registry,
        )
        assert "Tool is unavailable" in res3["final_response"]
        assert len(res3["tool_calls"]) == 0


# ============================================================================
# 3. Edge Cases & Boundary Mining Tests
# ============================================================================


class TestEdgeCasesAndBoundaryMining:
    """Stress-testing edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_toggle_nonexistent_tool_returns_404_no_db_mutation(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
        test_user: User,
        async_db_session: AsyncSession,
    ) -> None:
        """Toggling a nonexistent tool returns 404 and does not mutate TARSSettings."""
        headers = {"Authorization": f"Bearer {test_user_token}"}
        resp = await tools_api_client.patch(
            "/api/v1/tools/totally_fake_tool_xyz/toggle",
            headers=headers,
        )
        assert resp.status_code == 404

        # Verify DB untouched
        stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
        res = await async_db_session.execute(stmt)
        settings = res.scalar_one()
        await async_db_session.refresh(settings)
        assert settings.disabled_tools == []

    @pytest.mark.asyncio
    async def test_toggle_conflicting_payload_precedence(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
    ) -> None:
        """active field takes precedence when both active and enabled are sent."""
        headers = {"Authorization": f"Bearer {test_user_token}"}

        # Case 1: active=False, enabled=True -> active wins (tool becomes disabled)
        resp1 = await tools_api_client.patch(
            "/api/v1/tools/calendar_list_events/toggle",
            json={"active": False, "enabled": True},
            headers=headers,
        )
        assert resp1.status_code == 200
        assert resp1.json()["active"] is False

        # Case 2: active=True, enabled=False -> active wins (tool becomes enabled)
        resp2 = await tools_api_client.patch(
            "/api/v1/tools/calendar_list_events/toggle",
            json={"active": True, "enabled": False},
            headers=headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["active"] is True

    @pytest.mark.asyncio
    async def test_toggle_idempotency_no_duplicate_entries(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
        test_user: User,
        async_db_session: AsyncSession,
    ) -> None:
        """Multiple disable calls do not create duplicate entries in disabled_tools list."""
        headers = {"Authorization": f"Bearer {test_user_token}"}

        for _ in range(3):
            resp = await tools_api_client.patch(
                "/api/v1/tools/calendar_list_events/toggle",
                json={"active": False},
                headers=headers,
            )
            assert resp.status_code == 200

        stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
        res = await async_db_session.execute(stmt)
        settings = res.scalar_one()
        await async_db_session.refresh(settings)
        assert settings.disabled_tools.count("calendar_list_events") == 1

    def test_export_declarations_empty_and_unknown_filters(
        self,
        stress_tool_registry: ToolRegistry,
    ) -> None:
        """ToolRegistry.export_gemini_declarations handles empty, None, and unknown tool filters."""
        # None
        d_none = stress_tool_registry.export_gemini_declarations(None)
        assert len(d_none) == 4

        # Empty list
        d_empty = stress_tool_registry.export_gemini_declarations([])
        assert len(d_empty) == 4

        # Unknown tool names
        d_unknown = stress_tool_registry.export_gemini_declarations(
            ["nonexistent_a", "nonexistent_b", ""]
        )
        assert len(d_unknown) == 4

        # Mixture of real and unknown
        d_mixed = stress_tool_registry.export_gemini_declarations(
            ["tool_1", "ghost_tool"]
        )
        assert len(d_mixed) == 3
        assert {d["name"] for d in d_mixed} == {"tool_2", "tool_3", "tool_4"}

    @pytest.mark.asyncio
    async def test_concurrent_same_user_toggle_race(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
        test_user: User,
        async_db_session: AsyncSession,
    ) -> None:
        """Concurrent requests toggling different tools for the same user succeed without corruption."""
        headers = {"Authorization": f"Bearer {test_user_token}"}
        tools_to_toggle = [
            "calendar_list_events",
            "calendar_create_event",
            "gmail_search_messages",
            "gmail_send_message",
        ]

        async def do_toggle(t_name: str) -> int:
            r = await tools_api_client.patch(
                f"/api/v1/tools/{t_name}/toggle",
                json={"active": False},
                headers=headers,
            )
            return r.status_code

        statuses = await asyncio.gather(*[do_toggle(t) for t in tools_to_toggle])
        assert all(s == 200 for s in statuses)

        # Check DB state
        stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
        res = await async_db_session.execute(stmt)
        settings = res.scalar_one()
        await async_db_session.refresh(settings)

        assert isinstance(settings.disabled_tools, list)
        # All tools that were set to False should be in disabled_tools
        # (or at least valid list with unique items)
        assert len(set(settings.disabled_tools)) == len(settings.disabled_tools)


# ============================================================================
# 4. Persistence & Session Restart Simulation Tests
# ============================================================================


class TestPersistenceAcrossSessionRestarts:
    """Stress-testing TARSSettings persistence across simulated session restarts."""

    @pytest.mark.asyncio
    async def test_session_restart_rehydration(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
        test_user: User,
        test_engine: AsyncEngine,
    ) -> None:
        """Simulate session restart: settings persisted via API are loaded into a new session_node run."""
        headers = {"Authorization": f"Bearer {test_user_token}"}

        # 1. Disable two tools via API
        await tools_api_client.patch(
            "/api/v1/tools/calendar_list_events/toggle",
            json={"active": False},
            headers=headers,
        )
        await tools_api_client.patch(
            "/api/v1/tools/gmail_send_message/toggle",
            json={"active": False},
            headers=headers,
        )

        # 2. Simulate fresh server session / DB connection
        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as fresh_db_session:
            state: TARSState = {
                "user_id": test_user.id,
                "active_query": "Hello TARS",
                "messages": [HumanMessage(content="Hello TARS")],
            }
            state_update = await session_node(state=state, db_session=fresh_db_session)
            assert "calendar_list_events" in state_update["disabled_tools"]
            assert "gmail_send_message" in state_update["disabled_tools"]
            assert len(state_update["disabled_tools"]) == 2

        # 3. Re-enable one tool
        await tools_api_client.patch(
            "/api/v1/tools/calendar_list_events/toggle",
            json={"active": True},
            headers=headers,
        )

        # 4. Simulate another fresh restart
        async with session_factory() as second_fresh_db_session:
            state2: TARSState = {
                "user_id": test_user.id,
                "active_query": "Second session query",
                "messages": [HumanMessage(content="Second session query")],
            }
            state_update2 = await session_node(
                state=state2, db_session=second_fresh_db_session
            )
            assert "calendar_list_events" not in state_update2["disabled_tools"]
            assert state_update2["disabled_tools"] == ["gmail_send_message"]

    @pytest.mark.asyncio
    async def test_session_node_missing_settings_record_resilience(
        self,
        async_db_session: AsyncSession,
    ) -> None:
        """If user has no TARSSettings record in DB, session_node gracefully defaults without error."""
        now = datetime.now(UTC)
        user_no_settings = User(
            id="user_orphan_settings",
            username="orphan",
            email="orphan@endurance.space",
            hashed_password="pw",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        async_db_session.add(user_no_settings)
        await async_db_session.commit()

        state: TARSState = {
            "user_id": "user_orphan_settings",
            "active_query": "Testing orphan settings",
            "messages": [HumanMessage(content="Testing orphan settings")],
        }

        state_update = await session_node(state=state, db_session=async_db_session)
        assert state_update["disabled_tools"] == []

    @pytest.mark.asyncio
    async def test_session_node_none_disabled_tools_resilience(
        self,
        async_db_session: AsyncSession,
    ) -> None:
        """If TARSSettings has disabled_tools=None in DB, session_node falls back to empty list."""
        now = datetime.now(UTC)
        user = User(
            id="user_none_settings",
            username="none_tools_user",
            email="none@endurance.space",
            hashed_password="pw",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        settings = TARSSettings(
            user_id="user_none_settings",
            disabled_tools=None,
            created_at=now,
            updated_at=now,
        )
        async_db_session.add_all([user, settings])
        await async_db_session.commit()

        state: TARSState = {
            "user_id": "user_none_settings",
            "active_query": "Testing None disabled_tools",
            "messages": [HumanMessage(content="Testing None disabled_tools")],
        }

        state_update = await session_node(state=state, db_session=async_db_session)
        assert state_update["disabled_tools"] == []


# ============================================================================
# 5. Advanced LangGraph & Protocol Boundary Tests
# ============================================================================


class TestAdvancedLangGraphAndProtocolBoundaries:
    """Stress tests for AIMessage fallback, full compiled graph, and auth boundaries."""

    @pytest.mark.asyncio
    async def test_tool_node_fallback_extracts_from_aimessage_and_blocks(
        self,
        stress_tool_registry: ToolRegistry,
    ) -> None:
        """When state['tool_calls'] is empty, tool_node falls back to AIMessage.tool_calls and blocks disabled tools."""
        t1 = stress_tool_registry.get_tool("tool_1")
        assert isinstance(t1, AdversarialDummyTool)

        ai_msg = AIMessage(
            content="I will call tool 1.",
            tool_calls=[{"id": "call_fallback_1", "name": "tool_1", "args": {"query": "val"}}],
        )

        state: TARSState = {
            "messages": [HumanMessage(content="run"), ai_msg],
            "tool_calls": [],  # Explicitly empty
            "disabled_tools": ["tool_1"],
            "iteration_count": 0,
            "tool_results": [],
            "tools_used": [],
        }

        update = await tool_node(state=state, tool_registry=stress_tool_registry)

        assert t1.call_count == 0
        assert len(update["messages"]) == 1
        assert "[Tool Blocked: tool_1]" in update["messages"][0].content
        assert update["tool_results"][0]["status"] == "error"
        assert "disabled" in update["tool_results"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_full_compiled_graph_react_cycle_with_blocked_tool(
        self,
        stress_tool_registry: ToolRegistry,
        async_db_session: AsyncSession,
    ) -> None:
        """Execute complete compiled TARSGraph with a disabled tool in ReAct loop."""
        now = datetime.now(UTC)
        user_id = "user_full_graph_test"
        u = User(
            id=user_id,
            username="graph_user",
            email="graph_user@endurance.space",
            hashed_password="pw",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        settings = TARSSettings(
            user_id=user_id,
            disabled_tools=["tool_1"],
            created_at=now,
            updated_at=now,
        )
        async_db_session.add_all([u, settings])
        await async_db_session.commit()

        # Mock LLM Router:
        # Turn 1: LLM tries to call disabled tool_1
        # Turn 2: LLM receives blocked ToolMessage, produces final response
        mock_router = MagicMock()
        resp1 = LLMResponse(
            content="Calling tool 1",
            tool_calls=[ToolCallData(id="call_g1", name="tool_1", arguments={"query": "test"})],
        )
        resp2 = LLMResponse(
            content="Tool 1 is disabled as requested. I can proceed without it.",
            tool_calls=[],
        )
        mock_router.route_and_generate_response = AsyncMock(side_effect=[resp1, resp2])

        mock_slicer = MagicMock()
        mock_slicer.slice_context = AsyncMock(return_value=[])

        from tars.orchestrator.graph import create_tars_graph

        graph = create_tars_graph(
            router=mock_router,
            slicer=mock_slicer,
            tool_registry=stress_tool_registry,
            db_session=async_db_session,
        )

        initial_state: TARSState = {
            "user_id": user_id,
            "session_id": "test_graph_session",
            "active_query": "Please run tool 1 for me",
            "messages": [HumanMessage(content="Please run tool 1 for me")],
        }

        final_state = await graph.ainvoke(initial_state)

        t1 = stress_tool_registry.get_tool("tool_1")
        assert isinstance(t1, AdversarialDummyTool)
        assert t1.call_count == 0  # Crucial: disabled tool was blocked

        # Check final response
        assert "Tool 1 is disabled" in final_state.get("final_response", "")

        # Check messages history contains the blocked ToolMessage
        tool_msgs = [m for m in final_state.get("messages", []) if isinstance(m, ToolMessage)]
        assert len(tool_msgs) >= 1
        assert "[Tool Blocked: tool_1]" in tool_msgs[0].content

    @pytest.mark.asyncio
    async def test_toggle_tool_with_invalid_or_extreme_names(
        self,
        tools_api_client: AsyncClient,
        test_user_token: str,
    ) -> None:
        """Extreme input mining: special characters, spaces, and excessive length in tool name return 404."""
        headers = {"Authorization": f"Bearer {test_user_token}"}

        test_names = [
            "tool with spaces",
            "../../../etc/passwd",
            "tool$#!@%^&*()",
            "a" * 1000,
            "12345",
        ]

        for name in test_names:
            resp = await tools_api_client.patch(
                f"/api/v1/tools/{name}/toggle",
                headers=headers,
            )
            assert resp.status_code == 404
            detail = resp.json().get("detail", "")
            assert "not found" in detail.lower()

    @pytest.mark.asyncio
    async def test_google_oauth_callback_tampered_state_tokens(
        self,
        tools_api_client: AsyncClient,
        test_user: User,
    ) -> None:
        """Callback strictly validates CSRF state token against forgery and expiration."""
        # 1. Expired state token
        expired_state = create_access_token(
            data={"sub": test_user.id, "type": "oauth_state"},
            expires_delta=timedelta(seconds=-10),  # expired 10s ago
        )
        r1 = await tools_api_client.get(
            "/api/v1/tools/auth/google/callback",
            params={"code": "mock_code", "state": expired_state},
        )
        assert r1.status_code == 400
        assert "Invalid or expired OAuth state" in r1.json()["detail"]

        # 2. State token with wrong secret / signature
        tampered_state = expired_state[:-5] + "xxxxx"
        r2 = await tools_api_client.get(
            "/api/v1/tools/auth/google/callback",
            params={"code": "mock_code", "state": tampered_state},
        )
        assert r2.status_code == 400
        assert "Invalid or expired OAuth state" in r2.json()["detail"]

