# E2E Test Infra: TARS Vera & Miu Dual-Maid Group Chat System

## Test Philosophy
- Opaque-box, requirement-driven. Derived strictly from `ORIGINAL_REQUEST.md` (## 2026-09-16T23:25:07Z) and `docs/COGNITIVE_COMPANION_PLAN*.md`.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial + Real-World Workload Testing.
- Zero tolerance for mock dialogues: verify authentic LLM execution, proper token event tags, and real-time protocol timings.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Mock Dialogue Eradication | R1 (companion.py:126-201) | 5 | 5 | ✓ |
| 2 | Authentic Dual LLM Inference | R1 (HybridLLMRouter) | 5 | 5 | ✓ |
| 3 | Perspective Prompt Injection | R1 (PersonaRegistry) | 5 | 5 | ✓ |
| 4 | Companion Graph Service Wiring | R2 (AgentChatService) | 5 | 5 | ✓ |
| 5 | Stream Event Metadata Tagging | R2 (AgentStreamEvent) | 5 | 5 | ✓ |
| 6 | Turn Lock & Monotonic Epoch | R2 (HybridSessionTurnLock) | 5 | 5 | ✓ |
| 7 | Overlapped Prefetch & Bâton Touch | R2 (PrefetchBufferQueue) | 5 | 5 | ✓ |
| 8 | KakaoTalk Read Receipt Protocol | R3 (2->1->0 timing) | 5 | 5 | ✓ |
| 9 | Typing Indicator Protocol | R3 (Secondary prefetch) | 5 | 5 | ✓ |
| 10 | Companion Avatar Assets | R4 (static/avatars) | 5 | 5 | ✓ |
| 11 | Dual-Maid Group Chat UI Layout | R4 (index.html/components.css) | 5 | 5 | ✓ |
| 12 | Multi-Speaker Session Restoration | R4 (REST messages + UI) | 5 | 5 | ✓ |

## Test Architecture
- Test runner: `./.venv/bin/pytest tests/ -o asyncio_mode=auto -v`
- Pass/fail semantics: 100% test pass rate, 0 failures, 0 errors, 0 integrity violations.
- Test directory structure:
  - `tests/tier1_unit/`: Isolated unit tests for LLM generation, prompt injection, schemas, turn locks, prefetch queue, and avatar assets.
  - `tests/tier2_integration/`: Multi-turn integration tests for `AgentChatService.stream_chat()` driving `create_companion_graph`, WebSocket reader/dispatcher, and protocol timings.
  - `tests/tier3_e2e_api/`: End-to-end API and WebSocket streaming tests asserting read receipts (`2` -> `1` -> `0`), typing indicator frames, speaker tagging, and session history restoration.
  - `tests/tier4_application/`: Full application scenarios verifying group chat conversation flows, multi-turn banter, and barge-in interruption.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Master's Exhausting Day (Tag-Team Remediation) | F1, F2, F3, F4, F5, F7, F8, F9, F11 | High |
| 2 | Debate & Banter (Vera & Miu Collaborative Turn) | F2, F3, F6, F7, F8, F9, F11 | High |
| 3 | User Barge-In Interruption Mid-Stream | F5, F6, F7, F8, F11 | High |
| 4 | Rapid Multi-Message Burst & Read Receipts | F6, F8, F9, F11 | Medium |
| 5 | Past Conversation Restoration & Continuous Chat | F4, F10, F11, F12 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature (Total: ≥60 unit tests)
- Tier 2: ≥5 per feature with boundaries (Total: ≥60 integration tests)
- Tier 3: Pairwise coverage of major feature combinations (Total: ≥12 E2E tests)
- Tier 4: ≥5 realistic application scenarios
- **Total test suite target**: ≥137 test cases
