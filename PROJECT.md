# Project: TARS Vera & Miu Dual-Maid Group Chat System

## Architecture
The TARS Vera & Miu Dual-Maid Group Chat System transforms TARS from a legacy single-assistant terminal chatbot into an authentic multi-companion cognitive group chat environment:
1. **Cognitive Orchestration Layer (`tars/engine/orchestrator/graphs/companion.py`)**:
   - Zero Mock Policy: Complete eradication of `_generate_character_response()` and all canned Korean f-strings.
   - Genuine Dual LLM Inference: Vera (System 2, rational task maid) and Miu (System 1, emotional cat maid) are rendered via `PersonaRegistry.render_system_prompt()` injecting `master_state`, `context_summary`, `prev_vibe`, and `perspective_context`, invoking `HybridLLMRouter` independently.
   - Clean state-only `_synthesize_inner_state()` producing `CharacterInnerState(my_vibe, my_agenda)` without synthetic dialogue.
   - Transparent error propagation: Circuit-breaker fallback to local SLM or explicit error stream frame (never fake dialogue).
2. **Service & Streaming Layer (`tars/domains/chat/services/agent_chat.py`, `stream_bridge.py`)**:
   - `AgentChatService.stream_chat()` rewired to execute `create_companion_graph` with `CompanionState`.
   - `AgentStreamEvent` metadata enrichment: `speaker` ("vera" | "miu"), `avatar`, `turn_epoch`, and `turn_state`.
   - `LangGraphStreamBridge` custom event capture for companion node streaming.
3. **Concurrency & Real-Time Protocols (`tars/runtime/`, `tars/domains/chat/router.py`)**:
   - `HybridSessionTurnLock`: L1 `asyncio.Lock` + L2 Redis `SET NX PX 15000` with 15s watchdog, 3s heartbeat, monotonic `turn_epoch`, and 0ms barge-in token drop.
   - `PrefetchBufferQueue`: Overlapped prefetch of secondary speaker triggered by sentence punctuation or 30 tokens; 0.2s organic breathing jitter bâton touch delivery.
   - KakaoTalk Read Receipt Protocol: Client paints yellow `2` on send; Vera emits `read_receipt` at 0.05s (`unread_count: 1`); Miu emits `read_receipt` at 0.3~0.5s jitter (`unread_count: 0`).
   - Real-time Typing Indicator Protocol: Secondary speaker prefetch triggers `{"type": "typing_indicator", "sender": "miu", "status": "active"}`.
4. **Headless Backend Architecture Transition (`tars/static/` Decommissioned)**:
   - Static test web application (`tars/static/`) and PWA serving routes purged to streamline TARS into a pure Headless Cognitive Companion API & WebSocket server.
   - Persona avatar identifiers and metadata preserved in backend schema for client consumers.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Mock Eradication | Permanently remove `_generate_character_response()` and all mock f-strings | M1 | Survey (R1) |
| 2 | Inner State Synthesis | State-only `_synthesize_inner_state()` producing `CharacterInnerState` | M1 | Survey (R1) |
| 3 | Genuine Dual LLM Inference | Primary & secondary companions invoke `HybridLLMRouter` independently | M1 | Survey (R1) |
| 4 | Perspective Prompt Injection | Inject `master_state`, `context_summary`, `prev_vibe`, `perspective_context` | M1 | Survey (R1) |
| 5 | Explicit Error Propagation | Circuit breaker fallback to local SLM or explicit error frame (no mock fallback) | M1 | Survey (R1) |
| 6 | Companion Graph Service Wiring | `AgentChatService.stream_chat()` executes `create_companion_graph` | M2 | Survey (R2) |
| 7 | Stream Event Metadata Tagging | Add `speaker`, `avatar`, `turn_epoch`, `turn_state` to `AgentStreamEvent` | M2 | Survey (R2) |
| 8 | Stream Bridge Event Capture | `stream_bridge.py` forwards companion custom events and node outputs | M2 | Survey (R2) |
| 9 | Turn Lock & Monotonic Epoch | `HybridSessionTurnLock` L1/L2 arbitration and 0ms token drop | M2 | Survey (R2) |
| 10 | Overlapped Prefetch & Bâton Touch | `PrefetchBufferQueue` punctuation/30-token trigger + 0.2s breathing delay | M2 | Survey (R2) |
| 11 | KakaoTalk Read Receipt Protocol | Server emits Vera (0.05s, unread=1) and Miu (0.3~0.5s, unread=0) | M3 | Survey (R3) |
| 12 | Typing Indicator Protocol | Server emits `typing_indicator` on secondary prefetch trigger | M3 | Survey (R3) |
| 13 | WebSocket Wire Schemas | `WSMessageOut` extended with speaker, avatar, epoch, reader, unread_count | M3 | Survey (R3) |
| 14 | Companion Avatar Assets | Create `vera.png`, `vera.svg`, `miu.png`, `miu.svg` in `tars/static/avatars/` | M4 | Survey (R4) |
| 15 | Legacy UI Eradication | Purge all `TARS // AI`, mode selectors, scanlines, and single-bot HUD | M4 | Survey (R4) |
| 16 | Header & Presence Bar | Header with Vera (🧊) & Miu (🐾) profiles, online status, live typing | M4 | Survey (R4) |
| 17 | Gemini-Style Date Sidebar | Accordion list (오늘, 어제, 지난 7일 등) with `[+ New Chat]` and active state | M4 | Survey (R4) |
| 18 | Dual-Maid Speech Bubbles | User right with yellow badge; Vera left formal maid; Miu left cute cat | M4 | Survey (R4) |
| 19 | Streaming Cursor & Indicator UI | Blinking cursor in active bubble + floating typing indicator banner | M4 | Survey (R4) |
| 20 | Multi-Speaker Session Restore | Reconstruct past sessions with speaker separation, avatars, and badges | M4 | Survey (R4) |
| 21 | PWA Service Worker v4.0.0 | Cache update in `sw.js` and manifest updates | M4 | Survey (R4) |
| 22 | Comprehensive E2E Verification | 100% E2E test suite pass (Tiers 1-4) + Tier 5 coverage hardening | M5 | Master Plan |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test suite (Tiers 1-4), test runner, publishes `TEST_READY.md` | none | DONE |
| M1 | Mock Dialogue Eradication & Dual LLM Inference | Features 1-5: Clean `companion.py`, `HybridLLMRouter`, `PersonaRegistry` injection | none | DONE |
| M2 | Companion Graph Service Wiring & Concurrency | Features 6-10: `AgentChatService.stream_chat()`, `AgentStreamEvent`, `PrefetchBufferQueue` | M1 | DONE |
| M3 | KakaoTalk Read Receipt & Typing Indicator Protocol | Features 11-13: WebSocket read receipts (2->1->0), typing indicators, schemas | M2 | DONE |
| M4 | Static Test App Decommission & Headless Transition | Purged tars/static, removed PWA routes, consolidated pure Headless API | M3 | DONE |
| M5 | Final E2E Pass & Coverage Hardening | Feature 22: 100% E2E test suite pass (Tiers 1-4) + Tier 5 adversarial hardening | E2E, M1, M2, M3, M4 | DONE |

## Interface Contracts

### M1 (Companion Graph) ↔ M2 (AgentChatService)
- `create_companion_graph(router, slicer, registry, session_manager, db_session, storage_manager)` returns compiled LangGraph.
- Initial state schema: `CompanionState` with `messages`, `user_id`, `session_id`, `active_query`, `active_persona_ids=["vera", "miu"]`.
- Emission contract: Custom stream events tagged with `{"speaker": "vera" | "miu", "avatar": str, "turn_epoch": int, "turn_state": str}`.

### M2 (Service Layer) ↔ M3 (WebSocket Protocol)
- `AgentStreamEvent`:
  - `speaker: str | None = None`
  - `avatar: str | None = None`
  - `turn_epoch: int | None = None`
  - `to_ws_dict()` serializes `speaker`, `avatar`, `turn_epoch`.
- Read receipt payload:
  `{"type": "read_receipt", "message_id": str, "reader": "vera" | "miu", "unread_count": int, "session_id": str}`
- Typing indicator payload:
  `{"type": "typing_indicator", "sender": "miu" | "vera", "status": "active" | "inactive", "label": str}`

### M3 (Protocol) ↔ M4 (Frontend Client)
- Client sends:
  `{"type": "chat_message", "session_id": str, "content": str, "message_id": str}`
- Client handles:
  - `read_receipt`: update message's yellow badge (`2` -> `1` -> remove).
  - `typing_indicator`: show/hide typing indicator banner and header badge.
  - `stream_start`: create speech bubble for `frame.speaker` ("vera" or "miu").
  - `token`: append delta to active bubble for `frame.speaker`.
  - `stream_end`: finalize active bubble for `frame.speaker`.

## Code Layout
- `tars/engine/orchestrator/graphs/companion.py`: Companion LangGraph, dual LLM inference, mock eradication
- `tars/domains/persona/registry.py`: `PersonaRegistry`, prompt templates
- `tars/domains/chat/services/agent_chat.py`: `AgentChatService.stream_chat()` wiring
- `tars/engine/orchestrator/schemas.py`: `AgentStreamEvent` metadata
- `tars/engine/orchestrator/stream_bridge.py`: `LangGraphStreamBridge`
- `tars/runtime/turn_lock.py`: `HybridSessionTurnLock`
- `tars/runtime/prefetch_queue.py`: `PrefetchBufferQueue`
- `tars/domains/chat/router.py`: WebSocket `/api/v1/chat/ws`, read receipt & typing protocols
- `tars/domains/chat/schemas.py`: `WSMessageOut`
- `tests/tier1_unit/`: Unit tests for companion LLM generation, schemas, turn locks
- `tests/tier2_integration/`: Integration tests for stream wiring, prefetch queue, read receipt timing
- `tests/tier3_e2e_api/`: E2E tests for WebSocket chat streaming and REST session endpoints
- `tests/tier4_application/`: Multi-turn conversational flow tests
