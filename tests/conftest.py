"""Global pytest fixtures and testing infrastructure for TARS.

Provides asynchronous database sessions, isolated file storage directories,
mock LLM adapters, test users, and sample OKF documents.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Generator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tars.adapters.base import BaseLLMAdapter
from tars.api.app import create_app
from tars.api.dependencies import get_db_session, get_storage_manager
from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.core.security import create_access_token, get_password_hash
from tars.db.base import Base
from tars.db.models import TARSSettings, User
from tars.storage.manager import FileStorageManager

# ============================================================================
# Pytest Asyncio Configuration
# ============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# File Storage Fixtures
# ============================================================================


@pytest.fixture
def temp_storage_root(tmp_path: Path) -> Path:
    """Provide an isolated temporary directory root for file storage operations."""
    storage_path = tmp_path / "tars_storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


@pytest.fixture
def temp_storage_dir(temp_storage_root: Path) -> Path:
    """Alias fixture for temporary storage root."""
    return temp_storage_root


@pytest.fixture
def storage_manager(temp_storage_root: Path) -> FileStorageManager:
    """Provide a FileStorageManager configured with an isolated temp storage directory."""
    return FileStorageManager(base_dir=temp_storage_root)


@pytest.fixture
def test_storage_manager(storage_manager: FileStorageManager) -> FileStorageManager:
    """Alias for storage_manager."""
    return storage_manager


# ============================================================================
# Database Engine & Session Fixtures (In-Memory SQLite)
# ============================================================================


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a pristine in-memory SQLite async database engine for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an active SQLAlchemy AsyncSession with automatic transaction rollback."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_db_session: AsyncSession) -> AsyncSession:
    """Convenience alias fixture for async_db_session."""
    return async_db_session


# ============================================================================
# Authentication & User Fixtures
# ============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_test_user(async_db_session: AsyncSession) -> User:
    """Create and persist primary test user (Cooper) with default TARS settings."""
    now = datetime.now(UTC)
    user_id = "user_test_alpha"
    user = User(
        id=user_id,
        username="cooper",
        email="cooper@endurance.space",
        hashed_password=get_password_hash("TarsPassword123!"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    settings = TARSSettings(
        user_id=user_id,
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
        created_at=now,
        updated_at=now,
    )

    async_db_session.add(user)
    async_db_session.add(settings)
    await async_db_session.commit()
    await async_db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def seed_second_user(async_db_session: AsyncSession) -> User:
    """Create and persist secondary test user (Brand) for multi-tenant isolation tests."""
    now = datetime.now(UTC)
    user_id = "user_test_beta"
    user = User(
        id=user_id,
        username="brand",
        email="brand@endurance.space",
        hashed_password=get_password_hash("BrandPassword123!"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    settings = TARSSettings(
        user_id=user_id,
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
        created_at=now,
        updated_at=now,
    )

    async_db_session.add(user)
    async_db_session.add(settings)
    await async_db_session.commit()
    await async_db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def test_user(seed_test_user: User) -> User:
    """Alias fixture for primary test user."""
    return seed_test_user


@pytest.fixture
def test_user_token(seed_test_user: User) -> str:
    """Generate a valid signed JWT access token for the primary test user."""
    return create_access_token(data={"sub": seed_test_user.id})


@pytest.fixture
def auth_headers(test_user_token: str) -> dict[str, str]:
    """Generate Authorization headers dictionary for authenticated requests."""
    return {"Authorization": f"Bearer {test_user_token}"}


# ============================================================================
# FastAPI AsyncClient Fixtures
# ============================================================================


@pytest_asyncio.fixture(scope="function")
async def api_client(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an AsyncClient with mocked database and storage dependencies."""
    app = create_app()

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def auth_client(
    api_client: AsyncClient,
    test_user_token: str,
) -> AsyncClient:
    """Return api_client with Authorization Bearer header pre-configured."""
    api_client.headers.update({"Authorization": f"Bearer {test_user_token}"})
    return api_client


# ============================================================================
# Mock LLM Adapters
# ============================================================================


class MockLLMAdapter(BaseLLMAdapter):
    """High-fidelity mock LLM adapter for offline deterministic unit/integration testing."""

    def __init__(
        self,
        name: str = "mock_adapter",
        default_responses: list[str] | None = None,
        canned_response: str | None = None,
        stream_chunks: list[str] | None = None,
        is_healthy_result: bool = True,
        simulated_delay: float = 0.0,
        simulate_delay: float | None = None,
        should_fail: bool = False,
    ) -> None:
        self.name = name
        self.canned_response = canned_response or "TARS: Affirmative. System ready."
        self.default_responses = default_responses or [self.canned_response]
        self.stream_chunks = stream_chunks or ["TARS: ", "Navigation ", "locked."]
        self._response_idx = 0
        self.is_healthy_result = is_healthy_result
        self.simulated_delay = simulate_delay if simulate_delay is not None else simulated_delay
        self.should_fail = should_fail
        self.call_history: list[dict[str, Any]] = []
        self.recorded_calls: list[dict[str, Any]] = self.call_history

    async def astream(
        self,
        messages: Sequence[Any],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Simulate real-time token chunk streaming."""
        self.call_history.append(
            {
                "method": "astream",
                "messages": list(messages),
                "system_prompt": system_prompt,
                "kwargs": kwargs,
            }
        )
        if self.should_fail:
            raise RuntimeError("Simulated SLM streaming error")
        if self.simulated_delay > 0:
            await asyncio.sleep(self.simulated_delay)

        if self.stream_chunks:
            for chunk in self.stream_chunks:
                yield chunk
        else:
            resp = self.default_responses[self._response_idx % len(self.default_responses)]
            self._response_idx += 1
            tokens = resp.split(" ")
            for i, token in enumerate(tokens):
                yield token if i == 0 else f" {token}"

    async def agenerate(
        self,
        messages: Sequence[Any],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Simulate full text response generation."""
        self.call_history.append(
            {
                "method": "agenerate",
                "messages": list(messages),
                "system_prompt": system_prompt,
                "kwargs": kwargs,
            }
        )
        if self.should_fail:
            raise RuntimeError("Simulated SLM generation error")
        if self.simulated_delay > 0:
            await asyncio.sleep(self.simulated_delay)

        resp = (
            self.canned_response
            or self.default_responses[self._response_idx % len(self.default_responses)]
        )
        self._response_idx += 1
        return resp

    async def is_healthy(self) -> bool:
        """Probe adapter health status."""
        if self.simulated_delay > 0:
            await asyncio.sleep(self.simulated_delay)
        return self.is_healthy_result

    async def check_health(self) -> bool:
        """Alias for is_healthy."""
        return await self.is_healthy()


# Class aliases for test suites
MockGeminiAdapter = MockLLMAdapter
MockLlamaCppAdapter = MockLLMAdapter


@pytest.fixture
def mock_gemini_adapter() -> MockLLMAdapter:
    """Provide a mock Gemini high-intelligence adapter."""
    return MockLLMAdapter(
        name="gemini_adapter",
        canned_response="Confirmed. Setting navigation trajectory through the wormhole. Humor is at 90%.",
        stream_chunks=["TARS: ", "Navigation ", "locked."],
        is_healthy_result=True,
    )


@pytest.fixture
def mock_llama_adapter() -> MockLLMAdapter:
    """Provide a mock llama.cpp local SLM adapter."""
    return MockLLMAdapter(
        name="llamacpp_adapter",
        canned_response="Copy that, Cooper. Standing by.",
        stream_chunks=["SLM: ", "Ready."],
        is_healthy_result=True,
        simulated_delay=0.001,
    )


@pytest.fixture
def mock_llamacpp_adapter(mock_llama_adapter: MockLLMAdapter) -> MockLLMAdapter:
    """Alias fixture for mock llama adapter."""
    return mock_llama_adapter


# ============================================================================
# Sample OKF Document Fixtures
# ============================================================================


@pytest.fixture
def sample_okf_text_valid() -> str:
    """Return a standard, fully valid OKF markdown document with YAML Frontmatter."""
    return """---
okf_version: "1.0"
id: "user_pref_001"
type: "preference"
title: "TARS Humor & Communication Rules"
category: "persona_settings"
tags:
  - "interstellar"
  - "humor"
  - "custom_rule"
importance: "high"
source: "auto_extracted"
relations:
  depends_on: []
  related_to:
    - "core_tars_persona"
    - "honesty_setting"
created_at: "2026-08-18T00:00:00Z"
updated_at: "2026-08-18T00:00:00Z"
---

# TARS Humor & Communication Rules

User prefers dry, deadpan wit in style of Interstellar.
- Maintain 90% humor setting
- Prohibit bubbly emojis and sycophancy
- Loyal execution with sharp sarcasm
"""


@pytest.fixture
def sample_okf_doc() -> OKFDocument:
    """Provide a parsed, fully typed OKFDocument instance for testing."""
    now = datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC)
    metadata = OKFMetadata(
        okf_version="1.0",
        id="schedule_weekly_sync",
        type=OKFType.RULE,
        title="Weekly Endurance Sync Meeting",
        category="operations",
        tags=["meeting", "sync", "endurance", "schedule"],
        importance=OKFImportance.HIGH,
        source=OKFSource.SYSTEM,
        relations=OKFRelations(
            depends_on=[],
            related_to=["flight_operations"],
        ),
        created_at=now,
        updated_at=now,
    )
    content = (
        "# Weekly Endurance Sync Meeting\n\n"
        "Meeting schedule: Tuesdays at 15:00 UTC.\n"
        "Agenda includes propulsion status, life support levels, and trajectory analysis."
    )
    return OKFDocument(metadata=metadata, content=content)
