# E2E Test Infra: TARS Phase 3

## Test Philosophy
- Opaque-box, requirement-driven, and robust against regressions.
- All testing runs in the `uv` virtual environment with `pytest`.
- Full coverage across 4 Tiers:
  - Tier 1: Unit & Feature Coverage (>=5 per feature)
  - Tier 2: Boundary & Corner Cases (>=5 per feature)
  - Tier 3: Cross-Feature Integration (Session + Tool + OKF)
  - Tier 4: Real-World End-to-End Application Scenarios

## Feature Inventory & Test Mapping
| # | Feature | Requirement | Tier 1 Unit | Tier 2 Boundary | Tier 3 Cross-Feature | Tier 4 Scenario |
|---|---------|-------------|:-----------:|:---------------:|:--------------------:|:---------------:|
| 1 | ChatSession & Message Models | R1 | 5 | 5 | ✓ | ✓ |
| 2 | Time Decay Routing (15m/2h) | R1 | 5 | 5 | ✓ | ✓ |
| 3 | Topic Shift & Natural Reset | R1 | 5 | 5 | ✓ | ✓ |
| 4 | Proactive Greeting Endpoint | R1 | 5 | 5 | ✓ | ✓ |
| 5 | Tool Base & Registry | R2 | 5 | 5 | ✓ | ✓ |
| 6 | Static Tool CAG Manager | R2 | 5 | 5 | ✓ | ✓ |
| 7 | MCP Client & Tool Adapter | R2 | 5 | 5 | ✓ | ✓ |
| 8 | Google Workspace Adapters | R2 | 5 | 5 | ✓ | ✓ |
| 9 | LangGraph ReAct & Fallback | R2 | 5 | 5 | ✓ | ✓ |
| 10 | 5-Factor Dynamic OKF Slicing | R3 | 5 | 5 | ✓ | ✓ |
| 11 | DB Fast Pre-filtering | R3 | 5 | 5 | ✓ | ✓ |
| 12 | Background Self-Evolution Loop | R3 | 5 | 5 | ✓ | ✓ |
| 13 | Real-time Knowledge Feedback | R3 | 5 | 5 | ✓ | ✓ |

## Test Architecture & Directory Layout
- `tests/tier1_unit/`:
  - `test_smart_session_models.py`
  - `test_time_decay_routing.py`
  - `test_topic_shift_and_reset.py`
  - `test_tool_registry_and_cag.py`
  - `test_google_workspace_adapters.py`
  - `test_mcp_client_adapter.py`
  - `test_dynamic_slicer_5factor.py`
- `tests/tier2_integration/`:
  - `test_langgraph_tool_react_loop.py`
  - `test_tool_error_graceful_fallback.py`
  - `test_knowledge_extractor_background.py`
  - `test_db_prefiltering_slicer.py`
- `tests/tier3_e2e_api/`:
  - `test_greeting_api.py`
  - `test_chat_session_lifecycle_api.py`
- `tests/tier4_application/`:
  - `test_full_conversation_loop.py` (Extended for Phase 3 Session + Tools + Auto-evolution)

## Test Execution Commands
- Full Suite: `uv run pytest tests/ -v`
- Strict Typing: `uv run mypy --strict tars/ tests/`
- Linting: `uv run ruff check tars/ tests/`
