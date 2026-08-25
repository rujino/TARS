# Project: TARS Phase 1 Core MVP

## Architecture
TARS Phase 1 Core MVP is structured as a segregated "Trinity Knowledge Layer" + LangGraph hybrid agent state machine + FastAPI real-time token streaming backend:

```
+-----------------------------------------------------------------------------------+
|                                 FastAPI Backend                                   |
|   +--------------------------+  +--------------------------+  +-----------------+ |
|   |  JWT Auth & Users API    |  |  TARS Persona Settings   |  | SSE / WebSocket | |
|   |  (/api/v1/auth)          |  |  (/api/v1/tars/config)   |  | (/api/v1/chat)  | |
|   +--------------------------+  +--------------------------+  +-----------------+ |
+------------------------------------------|----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                        LangGraph StateGraph Orchestrator                          |
|  [Dynamic Slicer Context] -> [TARS Persona System Prompt]                         |
|                                     |                                             |
|        +----------------------------+----------------------------+                |
|        v (Internal Tasks Only)                                   v (User Dialogue)|
|  [llama.cpp Adapter (Local SLM)]                      [Google Gemini Adapter]     |
|  - Intent classification / Query pre-processing       - User-Facing Response 100% |
|  - Entity extraction & internal reasoning only        - High intelligence & tools |
+-----------------------------------------------------------------------------------+
                                           | (User turn completed)
                                           v
+-----------------------------------------------------------------------------------+
|                 Self-Evolving Knowledge Extractor (Background Task)               |
|      Extracts preferences/rules/facts -> Formats OKF with source: "auto_extracted"|
+------------------------------------------|----------------------------------------+
                                           |
                    +----------------------+----------------------+
                    v                                             v
+---------------------------------------+     +-------------------------------------+
|   Segregated File Storage Layer       |     |  SQLAlchemy 2.0 Async Metadata DB   |
|   /storage/users/{user_id}/wikis/*.md | <-> |  user_wikis index, users, settings  |
|   (Pure Markdown Source of Truth)     |     |  (Fast querying & reconciliation)   |
+---------------------------------------+     +-------------------------------------+
```

### Database Schema & Migration Policy
- **MVP Development Phase (Current)**:
  - For rapid development, database initialization relies on `Base.metadata.create_all` executed in the FastAPI lifespan handler ([`tars/api/app.py`](file:///Users/jinhoryu/Workspace/SideProject/TARS/tars/api/app.py)).
  - Agents must **NOT** create Alembic migration versions/scripts (`alembic/versions/*.py`) during this phase.
- **Production Phase (Future)**:
  - Alembic migrations will be officially introduced for production deployment and data preservation.
- **Agent Guidelines**:
  - All models must maintain strict adherence to [`NAMING_CONVENTION`](file:///Users/jinhoryu/Workspace/SideProject/TARS/tars/db/base.py) in `tars/db/base.py` and SQLAlchemy 2.0 type conventions (`Mapped[...]`, `mapped_column`) to ensure zero-effort future Alembic `autogenerate` compatibility.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | OKF Parser & Serializer | Parse & serialize YAML frontmatter + markdown body conforming to `docs/OKF_SPEC.md` | M1 | R1, docs/OKF_SPEC.md |
| F2 | OKF Pydantic Models & Validator | Validate `okf_version`, `id`, `type`, `title`, `category`, `tags`, `importance`, `source`, `relations` | M1 | R1, docs/OKF_SPEC.md |
| F3 | Multi-Tenant File Storage Manager | User-isolated file operations (`/storage/users/{user_id}/wikis/*.md`), path traversal security, atomic write | M1 | R1, docs/ARCHITECTURE.md |
| F4 | SQLAlchemy 2.0 Async RDBMS Schema | Async models (`User`, `TARSSettings`, `UserWikiIndex`) with SQLite/PostgreSQL compatibility | M1 | R1, docs/TECH_STACK.md |
| F5 | Storage-DB Reconciliation Engine | Bidirectional sync & hash integrity check between markdown files and DB metadata index | M1 | R1, docs/ARCHITECTURE.md |
| F6 | OKF Dynamic Slicer | Multi-factor scoring (importance, tags, relations, context) & token budget dynamic prompt injection | M1 | R1, docs/PRD.md |
| F7 | TARS Persona System Prompt Engine | Dry wit (Humor 90%), extreme honesty (95%), companion/work modes, anti-sycophancy rules | M2 | R2, docs/PRD.md |
| F8 | Hybrid LLM Adapter Interface | Unified `BaseLLMAdapter` with `GeminiAdapter` (User-Facing 100% & Deep Reasoning) and `LlamaCppAdapter` (Lightweight Internal Tasks) | M2 | R2, docs/TECH_STACK.md |
| F9 | Tiered Internal Reasoning & 500ms Fallback | Smart tiered internal routing (SLM for fast pre-processing, Gemini for deep reasoning & user dialogue) with health-probe fallback | M2 | R2, docs/ARCHITECTURE.md |
| F10 | LangGraph StateGraph Pipeline | Complete state machine (`TARSState`, context injection, prompt composition, LLM streaming, memory preservation) | M2 | R2, docs/TECH_STACK.md |
| F11 | Prompt & Static Tool Schema Caching | Static CAG prompt / tool schema caching for cost and latency reduction | M2 | R2, docs/TECH_STACK.md |
| F12 | Self-Evolving Knowledge Extractor Worker | Async background task extracting facts/preferences/rules from conversation turns | M3 | R3, docs/PRD.md |
| F13 | Auto-Extracted OKF Persistence & Sync | Automatic formatting with `source: "auto_extracted"`, atomic `.md` persistence and DB indexing | M3 | R3, docs/OKF_SPEC.md |
| F14 | FastAPI Modular App & Lifespan | App initialization, Lifespan DB engine setup, CORS, global error handling & DI | M4 | R4, docs/TECH_STACK.md |
| F15 | JWT Authentication & User Routes | User signup, login, password hashing (bcrypt), JWT verification, `get_current_user` DI | M4 | R4, docs/PRD.md |
| F16 | TARS Persona Settings REST API | `GET`, `PATCH`, `POST /reset` endpoints for `humor_level`, `honesty_level`, `mode` | M4 | R4, docs/PRD.md |
| F17 | WebSocket Real-Time Token Streaming | `/api/v1/chat/ws` bidirectional token streaming protocol with lifecycle events | M4 | R4, docs/ARCHITECTURE.md |
| F18 | SSE Real-Time Token Streaming | `POST /api/v1/chat/stream` Server-Sent Events token stream endpoint | M4 | R4, docs/TECH_STACK.md |
| F19 | Strict Static Typing Configuration | 100% type annotations with Pydantic v2, TypedDict, Enum, passing `mypy --strict` | M4 | R5, pyproject.toml |
| F20 | 4-Tier E2E Test Suite & Hardening | Full unit, integration, streaming, and adversarial test suite passing 100% | M_Final | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Suite Track | Test infrastructure, fixtures, and Tier 1-4 tests for all F1-F20 features | none | DONE |
| M1 | OKF Engine & Segregated Storage | OKF parser/serializer/validator, file storage manager, async DB models & slicer (F1-F6) | none | DONE |
| M2 | LangGraph Orchestrator & TARS Persona | TARS persona prompt, LLM adapters (Gemini/Llama), hybrid router, StateGraph (F7-F11) | M1 | DONE |
| M3 | Self-Evolving Knowledge Extractor | Background knowledge extraction loop, auto-extracted OKF sync (F12-F13) | M1, M2 | DONE |
| M4 | FastAPI Backend & Streaming API | FastAPI setup, JWT auth, TARS config API, WebSocket & SSE streaming, pyproject.toml (F14-F19) | M1, M2, M3 | DONE |
| M_Final | Final Integration & Adversarial Hardening | Pass 100% E2E test suite (Tiers 1-4) + Tier 5 Adversarial Coverage Hardening (F20) | E2E, M1, M2, M3, M4 | DONE |

## Interface Contracts

### 1. OKF Engine & Models (`tars/core/okf/`)
```python
class OKFType(StrEnum):
    CONCEPT = "concept"
    RULE = "rule"
    ENTITY = "entity"
    PROCEDURE = "procedure"
    PREFERENCE = "preference"

class OKFImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class OKFSource(StrEnum):
    MANUAL = "manual"
    AUTO_EXTRACTED = "auto_extracted"
    SYSTEM = "system"

class OKFRelations(BaseModel):
    depends_on: list[str] = Field(default_factory=list)
    related_to: list[str] = Field(default_factory=list)

class OKFMetadata(BaseModel):
    okf_version: str = "1.0"
    id: str
    type: OKFType
    title: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: OKFImportance = OKFImportance.MEDIUM
    source: OKFSource
    relations: OKFRelations = Field(default_factory=OKFRelations)
    created_at: datetime
    updated_at: datetime

class OKFDocument(BaseModel):
    metadata: OKFMetadata
    content: str

def parse_okf_text(raw_text: str) -> OKFDocument: ...
def serialize_okf_document(doc: OKFDocument) -> str: ...
```

### 2. Storage & Dynamic Slicer (`tars/storage/`, `tars/slicer/`)
```python
class IFileStorageManager(Protocol):
    async def save_okf_file(self, user_id: str, doc: OKFDocument) -> Path: ...
    async def read_okf_file(self, user_id: str, okf_id: str) -> OKFDocument: ...
    async def delete_okf_file(self, user_id: str, okf_id: str) -> bool: ...
    async def list_okf_files(self, user_id: str) -> list[OKFDocument]: ...

class DynamicSlicerEngine:
    async def slice_context(
        self, user_id: str, query: str, active_tags: list[str], token_budget: int = 1500
    ) -> list[OKFDocument]: ...
```

### 3. LLM Adapters & LangGraph State (`tars/adapters/`, `tars/orchestrator/`)
```python
class BaseLLMAdapter(ABC):
    @abstractmethod
    async def astream(self, messages: list[BaseMessage], system_prompt: str) -> AsyncIterator[str]: ...
    @abstractmethod
    async def is_healthy(self) -> bool: ...

class TARSState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    humor_level: float      # 0.90
    honesty_level: float    # 0.95
    mode: str               # "companion" | "work"
    relevant_wikis: list[OKFDocument]
    system_prompt: str
    final_response: str
```

### 4. Self-Evolving Knowledge Extractor (`tars/extractor/`)
```python
class KnowledgeExtractionResult(BaseModel):
    extracted: bool
    documents: list[OKFDocument]

class SelfEvolvingKnowledgeWorker:
    async def extract_and_sync(self, user_id: str, conversation_turns: list[BaseMessage]) -> list[OKFDocument]: ...
```

## Code Layout
```
/Users/jinhoryu/Workspace/SideProject/TARS/
├── pyproject.toml                      # Project metadata, dependencies, mypy/pytest config
├── README.md
├── docs/                               # Specifications and architectural blueprints
│   ├── OKF_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── PRD.md
│   └── TECH_STACK.md
├── tars/                               # Core application package
│   ├── __init__.py
│   ├── config.py                       # Application settings (Pydantic BaseSettings)
│   ├── core/
│   │   ├── __init__.py
│   │   └── okf/                        # OKF models, parser, serializer, validator, errors
│   │       ├── __init__.py
│   │       ├── models.py
│   │       ├── parser.py
│   │       ├── serializer.py
│   │       └── validator.py
│   ├── db/                             # SQLAlchemy 2.0 Async DB models, session, engine
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models.py                   # User, TARSSettings, UserWikiIndex
│   ├── storage/                        # File storage management & multi-tenant isolation
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── reconciliation.py
│   ├── slicer/                         # Dynamic Knowledge Slicer
│   │   ├── __init__.py
│   │   └── engine.py
│   ├── persona/                        # TARS Persona system prompt generator
│   │   ├── __init__.py
│   │   └── prompts.py
│   ├── adapters/                       # Gemini & llama.cpp LLM adapters
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── gemini.py
│   │   ├── llamacpp.py
│   │   └── router.py
│   ├── orchestrator/                   # LangGraph StateGraph pipeline
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   └── graph.py
│   ├── extractor/                      # Async Self-Evolving Knowledge Extractor
│   │   ├── __init__.py
│   │   └── worker.py
│   └── api/                            # FastAPI app, routers, dependencies, streaming
│       ├── __init__.py
│       ├── app.py
│       ├── dependencies.py
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── auth.py
│       │   ├── tars_config.py
│       │   └── chat_stream.py
│       └── schemas/
│           ├── __init__.py
│           ├── auth.py
│           ├── config.py
│           └── chat.py
└── tests/                              # 4-Tier Test Suite
    ├── conftest.py                     # Async DB, mock LLM, temp storage fixtures
    ├── tier1_unit/                     # Tier 1: Feature unit tests (OKF, storage, persona, etc.)
    │   ├── test_okf_engine.py
    │   ├── test_storage_manager.py
    │   ├── test_db_reconciliation.py
    │   ├── test_dynamic_slicer.py
    │   └── test_persona_prompt.py
    ├── tier2_integration/              # Tier 2: Integration tests
    │   ├── test_llm_adapters.py
    │   ├── test_langgraph_pipeline.py
    │   └── test_knowledge_extractor.py
    ├── tier3_e2e_api/                  # Tier 3: FastAPI REST & Streaming tests
    │   ├── test_auth_api.py
    │   ├── test_config_api.py
    │   ├── test_websocket_streaming.py
    │   └── test_sse_streaming.py
    └── tier4_application/              # Tier 4: Realistic end-to-end self-evolving workflows
        ├── test_full_conversation_loop.py
        └── test_multi_tenant_isolation.py
```
