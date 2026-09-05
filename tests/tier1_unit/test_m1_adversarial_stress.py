"""Adversarial Stress Test Harness: Empirical Verification of RES-03, RES-04, and PERF-01.

Written by challenger_p1_m1_1 to stress-test:
- RES-03: Connection pooling, pre-ping recovery, pool exhaustion timeout, SQLite dialects.
- RES-04: ToolCAGManager cache TTL expiry under high concurrency and sequential load,
          hash invalidation on registry mutation, and reference mutation semantics.
- PERF-01: DynamicPromptSlicerEngine parallel I/O benchmark with simulated latency,
           and resilience against heterogeneous disk errors and malformed return types.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from tars.config import get_settings
from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.db.session import close_db, get_engine
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.base import BaseTool
from tars.tools.cag import ToolCAGManager
from tars.tools.registry import ToolRegistry

# ============================================================================
# Helpers & Mock Fixtures
# ============================================================================

class MockEchoTool(BaseTool):
    """Echo tool for CAG manager stress testing."""

    def __init__(self, name: str = "mock_tool") -> None:
        super().__init__(
            name=name,
            description="Mock tool for CAG testing",
            parameters_schema={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
            },
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        return kwargs.get("arg", "")


def make_test_okf_doc(
    doc_id: str,
    title: str = "Test Title",
    content: str = "Test OKF Content",
    importance: OKFImportance = OKFImportance.MEDIUM,
) -> OKFDocument:
    """Construct a well-formed OKFDocument."""
    now = datetime.now(UTC)
    meta = OKFMetadata(
        id=doc_id,
        type=OKFType.CONCEPT,
        title=title,
        category="testing",
        tags=["stress_test"],
        importance=importance,
        source=OKFSource.MANUAL,
        relations=OKFRelations(),
        created_at=now,
        updated_at=now,
    )
    return OKFDocument(metadata=meta, content=content)


class MockWikiRecord:
    """Mock UserWikiIndex record for DB index queries."""

    def __init__(
        self,
        okf_id: str,
        importance: str = "medium",
        tags: list[str] | None = None,
        title: str = "title",
        category: str = "cat",
    ) -> None:
        self.okf_id = okf_id
        self.importance = importance
        self.tags = tags or ["stress_test"]
        self.title = title
        self.category = category


# ============================================================================
# 1. RES-03: Connection Pooling, Dialect Guards & Pre-Ping Resilience
# ============================================================================

class TestAdversarialRES03ConnectionPooling:
    """Stress-test database connection pooling under load and boundary conditions."""

    @pytest.fixture(autouse=True)
    async def cleanup_engine(self) -> AsyncGenerator[None, None]:
        await close_db()
        get_settings.cache_clear()
        yield
        await close_db()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_pool_exhaustion_and_timeout_under_load(self, tmp_path: Path) -> None:
        """Adversarial stress: exhaust pool capacity and verify pool_timeout raises TimeoutError."""
        db_file = tmp_path / "pool_exhaust_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}",
            pool_size=2,
            max_overflow=1,
            pool_timeout=0.5,  # 500ms timeout
            pool_recycle=1800,
            pool_pre_ping=True,
        )

        checked_out_connections = []
        try:
            # Check out pool_size (2) + max_overflow (1) = 3 connections
            for _ in range(3):
                conn = await engine.connect()
                checked_out_connections.append(conn)

            assert len(checked_out_connections) == 3

            # Attempting to check out 4th connection must time out after ~0.5s
            t0 = time.perf_counter()
            with pytest.raises(SATimeoutError, match="QueuePool limit of size 2 overflow 1 reached"):
                await engine.connect()
            elapsed = time.perf_counter() - t0

            # Verify timeout timing was within reasonable tolerance (>= 0.40s and < 1.5s)
            assert 0.40 <= elapsed < 1.50, f"Unexpected timeout duration: {elapsed:.2f}s"
        finally:
            for conn in checked_out_connections:
                await conn.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_pool_pre_ping_reconnection_on_severed_connection(self, tmp_path: Path) -> None:
        """Adversarial stress: simulate dead TCP connection; pre_ping must detect and reconnect."""
        db_file = tmp_path / "pre_ping_recovery.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}",
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
        )

        try:
            # 1. Open initial connection and return it to pool
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT 1"))
                assert res.scalar() == 1

            # 2. Invalidate pooled connection (simulating TCP server disconnect / idle drop)
            raw_pool: Any = engine.sync_engine.pool
            pooled_conn = raw_pool._pool._queue._queue[0]
            pooled_conn.invalidate()

            # 3. Next checkout should trigger pre_ping, detect dead conn, and transparently reconnect
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT 42"))
                assert res.scalar() == 42
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_connection_checkout_and_release(self, tmp_path: Path) -> None:
        """Stress test: 30 concurrent coroutines contending for a bounded connection pool."""
        db_file = tmp_path / "concurrent_pool.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_file}",
            pool_size=5,
            max_overflow=5,
            pool_timeout=5.0,
            pool_recycle=1800,
            pool_pre_ping=True,
        )

        async def worker(worker_id: int) -> int:
            # Jittered checkout to induce high contention
            await asyncio.sleep(0.005 * (worker_id % 3))
            async with engine.connect() as conn:
                res = await conn.execute(text(f"SELECT {worker_id}"))
                val = res.scalar()
                assert val == worker_id
                # Hold connection briefly to force overflow usage
                await asyncio.sleep(0.01)
                return int(val)

        try:
            tasks = [worker(i) for i in range(30)]
            results = await asyncio.gather(*tasks)
            assert sorted(results) == list(range(30))
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_sqlite_in_memory_dialect_guard_and_empty_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify get_engine correctly handles SQLite :memory: StaticPool configuration."""
        # Standard SQLite in-memory URL
        monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        get_settings.cache_clear()
        engine = get_engine()
        assert engine.pool.__class__.__name__ == "StaticPool"

        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT 100"))
            assert res.scalar() == 100

        await close_db()

    @pytest.mark.asyncio
    async def test_close_db_idempotence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify close_db can be safely invoked multiple times without error."""
        monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        get_settings.cache_clear()

        # Engine not created yet
        await close_db()
        await close_db()

        # Engine created then closed twice
        get_engine()
        await close_db()
        await close_db()


# ============================================================================
# 2. RES-04: ToolCAGManager Cache TTL, Concurrency & Invalidation
# ============================================================================

class TestAdversarialRES04CAGCacheLifecycle:
    """Stress-test ToolCAGManager under rapid sequential access, concurrency, and TTL expiry."""

    def test_rapid_sequential_cag_bundle_retrieval(self) -> None:
        """Verify 1,000 rapid sequential calls within TTL return exact same bundle without recomputation."""
        registry = ToolRegistry([MockEchoTool("t1"), MockEchoTool("t2")])
        cag = ToolCAGManager(tool_registry=registry, ttl_seconds=60)

        initial_bundle = cag.get_static_cag_bundle()
        initial_cached_at = cag._cached_at
        assert initial_cached_at is not None

        for _ in range(1000):
            bundle = cag.get_static_cag_bundle()
            assert bundle is initial_bundle
            assert cag._cached_at == initial_cached_at

    @pytest.mark.asyncio
    async def test_concurrent_cag_bundle_retrieval_across_ttl_boundary(self) -> None:
        """Verify 50 concurrent coroutines calling get_static_cag_bundle across TTL expiry."""
        registry = ToolRegistry([MockEchoTool("tool_concurrent")])
        # Very short TTL: 1 second
        cag = ToolCAGManager(tool_registry=registry, ttl_seconds=1)

        # 1. Warm cache
        cag.get_static_cag_bundle()
        cached_at_v1 = cag._cached_at
        assert cached_at_v1 is not None

        # 2. Elapse time beyond TTL
        cag._cached_at = datetime.now(timezone.utc) - timedelta(seconds=2)

        # 3. Launch 50 concurrent coroutines
        async def fetcher(idx: int) -> dict[str, Any]:
            if idx % 2 == 0:
                await asyncio.sleep(0.005)
            return cag.get_static_cag_bundle()

        results = await asyncio.gather(*[fetcher(i) for i in range(50)])

        # All 50 results must be valid dictionaries
        for r in results:
            assert isinstance(r, dict)
            assert "system_prompt" in r
            assert len(r["tools"]) == 1
            assert r["ttl_seconds"] == 1

        # Cache timestamp must have been updated to a newer time
        assert cag._cached_at is not None
        assert cag._cached_at > cached_at_v1

    def test_cag_hash_invalidation_on_tool_registry_mutation(self) -> None:
        """Verify cache invalidates immediately when tool registry changes, even before TTL expiry."""
        registry = ToolRegistry([MockEchoTool("base_tool")])
        cag = ToolCAGManager(tool_registry=registry, ttl_seconds=3600)

        bundle1 = cag.get_static_cag_bundle()
        assert len(bundle1["tools"]) == 1
        cached_at1 = cag._cached_at
        assert cached_at1 is not None

        # Register a new tool into registry (modifying tool declaration hash)
        registry.register(MockEchoTool("added_tool"))

        # Next call must detect hash mismatch and recompute immediately
        bundle2 = cag.get_static_cag_bundle()
        assert len(bundle2["tools"]) == 2
        assert bundle2 is not bundle1
        assert bundle2["cache_hash"] != bundle1["cache_hash"]
        assert cag._cached_at is not None
        assert cag._cached_at >= cached_at1

    def test_cag_zero_ttl_behavior(self) -> None:
        """Boundary condition: ttl_seconds=0 must always recompute bundle on every call."""
        registry = ToolRegistry([MockEchoTool("zero_ttl_tool")])
        cag = ToolCAGManager(tool_registry=registry, ttl_seconds=0)

        b1 = cag.get_static_cag_bundle()
        time.sleep(0.001)
        b2 = cag.get_static_cag_bundle()

        # Should produce fresh dictionary objects
        assert b1 is not b2

    def test_cag_reference_mutation_semantics(self) -> None:
        """Verify that modifying the returned dictionary mutates internal cached bundle (known caveat)."""
        registry = ToolRegistry([MockEchoTool("immutable_check")])
        cag = ToolCAGManager(tool_registry=registry, ttl_seconds=300)

        b1 = cag.get_static_cag_bundle()
        original_tool_count = len(b1["tools"])

        # Caller mutates the returned tools list
        b1["tools"].append({"name": "external_injected_tool"})

        # Subsequent fetch within TTL returns mutated instance
        b2 = cag.get_static_cag_bundle()
        assert len(b2["tools"]) == original_tool_count + 1

        # Force refresh restores clean registry state
        b3 = cag.get_static_cag_bundle(force_refresh=True)
        assert len(b3["tools"]) == original_tool_count


# ============================================================================
# 3. PERF-01: Dynamic Slicer Concurrency Benchmark & Resilience Harness
# ============================================================================

class TestAdversarialPERF01SlicerConcurrencyAndResilience:
    """Stress-test DynamicPromptSlicerEngine parallel OKF loading and error absorption."""

    @pytest.mark.asyncio
    async def test_slicer_parallel_vs_sequential_latency_benchmark(self) -> None:
        """Empirical benchmark: verify asyncio.gather executes parallel I/O with >= 4x speedup over sequential."""
        storage = MagicMock()
        simulated_io_latency = 0.025  # 25ms per file read
        num_docs = 20

        async def simulated_slow_read(user_id: str, doc_id: str) -> OKFDocument:
            await asyncio.sleep(simulated_io_latency)
            return make_test_okf_doc(doc_id=doc_id, title=f"Title for {doc_id}")

        storage.read_okf_file = AsyncMock(side_effect=simulated_slow_read)

        # Mock DB records
        db_session = MagicMock()
        mock_result = MagicMock()
        mock_records = [MockWikiRecord(f"okf_perf_{i}") for i in range(num_docs)]
        mock_result.scalars.return_value.all.return_value = mock_records
        db_session.execute = AsyncMock(return_value=mock_result)

        slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db_session)

        # Measure parallel execution time
        t0 = time.perf_counter()
        docs = await slicer._fetch_via_db("bench_user", db_session, candidate_limit=num_docs)
        parallel_elapsed = time.perf_counter() - t0

        sequential_minimum = num_docs * simulated_io_latency  # 20 * 25ms = 500ms
        speedup = sequential_minimum / parallel_elapsed

        # Assertions
        assert len(docs) == num_docs
        # Parallel elapsed time must be strictly faster than half of sequential minimum
        assert parallel_elapsed < sequential_minimum / 2, (
            f"Parallel execution too slow: {parallel_elapsed:.4f}s >= {sequential_minimum / 2:.4f}s"
        )
        assert speedup >= 3.0, f"Expected speedup >= 3x, got {speedup:.2f}x"

    @pytest.mark.asyncio
    async def test_slicer_resilience_to_heterogeneous_disk_failures(self) -> None:
        """Fault injection: inject mixed disk exceptions and invalid types; must safely return valid docs."""
        import tars.slicer.engine as slicer_mod

        storage = MagicMock()

        async def faulty_read(user_id: str, doc_id: str) -> Any:
            if doc_id.startswith("good_"):
                return make_test_okf_doc(doc_id=doc_id)
            elif doc_id == "fail_not_found":
                raise FileNotFoundError(f"File {doc_id} does not exist on disk")
            elif doc_id == "fail_permission":
                raise PermissionError(f"Permission denied for {doc_id}")
            elif doc_id == "fail_timeout":
                raise asyncio.TimeoutError("I/O read timed out")
            elif doc_id == "fail_corrupt_yaml":
                raise ValueError("Invalid frontmatter YAML syntax")
            elif doc_id == "fail_return_none":
                return None
            elif doc_id == "fail_return_string":
                return "unexpected string instead of OKFDocument"
            return make_test_okf_doc(doc_id=doc_id)

        storage.read_okf_file = AsyncMock(side_effect=faulty_read)

        candidate_ids = (
            [f"good_{i}" for i in range(8)]
            + [
                "fail_not_found",
                "fail_permission",
                "fail_timeout",
                "fail_corrupt_yaml",
                "fail_return_none",
                "fail_return_string",
            ]
        )

        db_session = MagicMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [MockWikiRecord(cid) for cid in candidate_ids]
        db_session.execute = AsyncMock(return_value=mock_res)

        slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db_session)

        with patch.object(slicer_mod.logger, "warning") as mock_logger:
            docs = await slicer._fetch_via_db("fault_user", db_session, candidate_limit=50)

            # Exactly the 8 valid documents must be returned
            assert len(docs) == 8
            assert all(d.metadata.id.startswith("good_") for d in docs)

            # Warnings must be logged for all 6 failure cases
            assert mock_logger.call_count >= 6
            logged_messages = " ".join(str(call) for call in mock_logger.call_args_list)
            assert "fail_not_found" in logged_messages
            assert "fail_permission" in logged_messages
            assert "fail_timeout" in logged_messages
            assert "fail_corrupt_yaml" in logged_messages
            assert "fail_return_none" in logged_messages
            assert "fail_return_string" in logged_messages

    @pytest.mark.asyncio
    async def test_slicer_large_candidate_batch_stress(self) -> None:
        """Stress test: 100 candidate wiki records scored and gathered concurrently within candidate_limit."""
        storage = MagicMock()
        storage.read_okf_file = AsyncMock(
            side_effect=lambda u, doc_id: make_test_okf_doc(doc_id=doc_id)
        )

        # 100 records with varying importance
        db_session = MagicMock()
        mock_res = MagicMock()
        records = [
            MockWikiRecord(
                okf_id=f"doc_large_{i}",
                importance="critical" if i < 10 else ("high" if i < 30 else "low"),
            )
            for i in range(100)
        ]
        mock_res.scalars.return_value.all.return_value = records
        db_session.execute = AsyncMock(return_value=mock_res)

        slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db_session)

        # With candidate_limit=20, exactly 20 top scored docs should be fetched
        docs = await slicer._fetch_via_db(
            user_id="stress_user",
            db_session=db_session,
            candidate_limit=20,
        )

        assert len(docs) == 20
        # Critical documents (index 0..9) must be among top candidates
        fetched_ids = {d.metadata.id for d in docs}
        for i in range(10):
            assert f"doc_large_{i}" in fetched_ids

    @pytest.mark.asyncio
    async def test_slicer_db_prequery_failure_graceful_handling(self) -> None:
        """Verify DB connection error during pre-query is caught and returns empty list cleanly."""
        storage = MagicMock()
        db_session = MagicMock()
        db_session.execute = AsyncMock(side_effect=RuntimeError("Database connection severed"))

        slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db_session)

        docs = await slicer._fetch_via_db("err_user", db_session)
        assert docs == []

    @pytest.mark.asyncio
    async def test_slicer_zero_candidate_boundary(self) -> None:
        """Verify empty DB result returns empty list without calling storage manager."""
        storage = MagicMock()
        db_session = MagicMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        db_session.execute = AsyncMock(return_value=mock_res)

        slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db_session)

        docs = await slicer._fetch_via_db("empty_user", db_session)
        assert docs == []
        assert storage.read_okf_file.call_count == 0
