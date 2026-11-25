# Kira T0–T5 Change and Integration History

This file is a historical handoff record. Its original development-stage statements about tests and runtime validation are retained as historical facts; they must not be interpreted as current test results.

## v7 — T0: Remove Chinese/Japanese source characters

**Finding:** only 13 lines in seven Python files contained Chinese/Japanese characters. They were functional characters, not explanatory prose.

**Change:** characters were represented with Unicode escapes (`\uXXXX`) and each occurrence received an English comment. Final string values and regex behavior were checked for semantic equivalence by comparing parsed ASTs and parsing the before/after regexes.

| File | Original content | Result |
|---|---|---|
| `kira/cloud_voice.py` | Sentence terminators `。！？` | Retained with a comment |
| `kira/emotion/parser.py` | Chinese keyword for “emotion” and `：` | Escaped with a comment |
| `kira/leak_guard.py` | Full-width colon (3 occurrences) | Retained with comments |
| `kira/persona_memory.py` | Full-width question mark (4 occurrences) | Retained with comments |
| `kira/speech_split.py` | `TERMS` and docstring text | Escaped and documented in English |
| `kira/strings.py` | Japanese TTS sample sentence | Escaped with an English translation comment |
| `kira/tools/tasks.py` | Full-width colon in “add a step” separator | Retained with a comment |

**Intentionally unchanged:** Persian user-facing text, Persian regexes, and `*_FA.md` documents. They are part of the product language and translating them would change behavior.

**Policy recorded at that stage:** new code, comments, and prompts should be written in English; only user-facing product text should remain Persian.

---

## v8 — T1: Evidence-based memory

Full documentation: `docs/MEMORY_EVIDENCE_FA.md`.

**New files**
- `kira/evidence_memory.py` — fact-plus-evidence storage, contradiction/uncertainty handling, BM25, optional embeddings, RRF, quarantine, and history backfill.
- `docs/MEMORY_EVIDENCE_FA.md`.

**Changed files**
- `kira/persona_memory.py` — `extract_facts_detailed` (existing rules plus quotations); `extract_facts` retains its previous output; `observe` also writes to the evidence layer; delete/edit/forget operations synchronize both layers; `build_block(query, budget)` falls back fully to the previous behavior.
- `kira/memory.py` — read-only `rows_with_ids` and `max_message_id`.
- `kira/main.py` — three integration points: configure at startup and after settings save, and pass the current message and budget to `build_block`.
- `kira/config.py` — five default settings.
- `kira/storage.py` — backup of `kira_evidence.sqlite3`.

**Intentionally unchanged:** Active Mode, character behavior, Relationship Memory (moments, habits, summaries), the memory window, Web Research, and Tasks.

**Not implemented at that stage:** automatic model calls for fact extraction (would consume API usage); an Embedding settings UI (out of scope).

**Windows validation requested by the original handoff**
1. First launch with an old database: verify creation of `kira_evidence.sqlite3` and no errors.
2. Memory window: add, edit, delete, and “forget everything”.
3. “My name is X” followed by “No, my name is Y”: only Y should enter the prompt.
4. With `embedding_backend=ollama` and a real model: measure first-message latency and behavior when Ollama is stopped.
5. Measure the actual memory block size with Qwen 3.5 4B at `num_ctx=4096`.

---

## v9 — T2: Multi-stage Brain

Documentation: `docs/BRAIN_FA.md`.

**New files:** `kira/brain.py`, `docs/BRAIN_FA.md`.

**Changed files**
- `kira/hybrid_ai.py` — `role_scope(role, route_id)`; the preferred route is tried first while existing order, failover, and cooldown behavior is retained; metrics include the `role` field.
- `kira/evidence_memory.py` — `current_value`, `writer_cursor`, and `set_writer_cursor`.
- `kira/main.py` — `StreamWorker(role, route_id)`; `start_worker` selects a stage and extends the prompt only when needed; `on_stream_done` calls `brain.after_turn`; `clear_chat` calls `brain.reset_state`.
- `kira/config.py` — four default settings.

**Intentionally not implemented:** rewriting a response after it is displayed, default automatic model calls, and a UI for `role_routes`.

**Windows validation requested:** verify the simple-message prompt is unchanged; Deep selection for long/analytical requests and no extra block for Qwen 4B at Context 4096; preferred Deep route behavior; one-time Reflection hints; and that optional model Reflection/background memory writing do not freeze the UI or exceed their limits.

---

## v10 — T3: MCP and independent agents

Documentation: `docs/MCP_AGENTS_FA.md`; example: `docs/kira_mcp.example.json`.

**New files:** `kira/mcp/{__init__,config,client,hub,agents}.py`, plus the two documentation/reference files above.

**Changed files**
- `kira/tools/registry.py` — lock and `unregister_where` for registering tools from a background thread.
- `kira/tools/protocol.py` — `mcp` and `agents` categories, `set_gate_words`, and conditional `MCP_RULES`.
- `kira/tools/agent.py` — guarded `install` in `ToolAgent.__init__`, tool labels, and MCP rules.
- `kira/config.py` — `mcp_mode`.

**Intentionally not implemented:** model-driven server registration, UI, OAuth, and automatic task-completion notifications.

**Windows validation:** see the checklist in `docs/MCP_AGENTS_FA.md`.

---

## v11 — T4: Usage and cost tracking

Documentation: `docs/USAGE_FA.md`.

**New file:** `kira/usage.py` and its documentation.

**Changed files**
- `kira/hybrid_ai.py` — provider `last_usage` and `_note_usage`; `stream_options.include_usage` for Groq/OpenRouter; `_ledger` in `_finish` and the all-routes-failed path; limit enforcement in `_candidates`.
- `kira/main.py` — `usage.install` at startup and after settings save, plus the `/usage` command.
- `kira/config.py` — `model_prices` and `usage_limits`.
- T1/T2 hooks (`evidence_memory.usage_hook`, `brain.budget_check`) are connected.

**Intentionally not implemented:** usage UI, token estimation from text length, and interrupting a conversation because a limit is reached.

**Windows validation:** see `docs/USAGE_FA.md`.

---

## v12 — T0–T4 integration

**Audit (before the original Stage 10 test run):** the import graph was reviewed and no import-time cycle was found; `kira.mcp` is loaded lazily by `ToolAgent`. New data is stored under `DATA_DIR` (`%LOCALAPPDATA%\Kira`) and survives application updates: `kira_evidence.sqlite3`, `kira_brain_state.json`, `kira_jobs.json`, `kira_usage.sqlite3`, and `kira_mcp.json`.

**Fixes**
1. Automatic planner (`autonomy._cats_for`): without a detected category, MCP and agent catalogs are not added to the prompt; they are included only when their names are mentioned.
2. `brain.check_reply`: “requires confirmation” is no longer treated as “concealed error” (only error/denied/bad_args/unknown are).
3. `brain._small_context`: Route preview runs inside the correct role scope (detects a small local model on the Deep role's route).
4. Local Ollama embeddings are recorded as “local” in usage accounting, not Unknown.
5. `agent_ask`: unknown agents are reported before quote validation.
6. `model_prices` accepts a provider-only price key.
7. MCP subprocess pipes are released during shutdown.
8. References to the upstream reference project were removed from code and docs; the change record was renamed to `CHANGES_INTEGRATION_FA.md`; README was updated with the new documentation list.

**Tests recorded for the original Stage 10**
- New `tests/test_integration_t0_t4.py`: 27 tests covering memory supersession and invalid-quote rejection; Brain stage selection, one-time hints, and state persistence; role routing and failover; usage (reported tokens, Unknown, cost, failure, provider/role limits); MCP with a real stdio server (default permissions, ignored annotations, key-free environment, allow/deny, broken server); agents with a local HTTP server (quotes, confirmation, idempotency, user response, health, restart, stop); and ToolAgent wiring.
- The historical report said the previous suite was green except for items that were already the same in v6: `test_image_search` (PySide6 required), `test_release::requirements` (legacy test did not know about `psutil`), and three `test_streaming` cases (tests expected separate chunks while LeakGuard combined the first characters; one case showed that a disconnect after a very short response could enter failover).
- GUI tests requiring PySide6 were skipped in that environment.

**Still requiring Windows 11 validation at that stage:** the checklists in `MEMORY_EVIDENCE_FA`, `BRAIN_FA`, `MCP_AGENTS_FA`, and `USAGE_FA`, plus full GUI startup and `run_tests.bat`.

---

## v13 — T5-A: File Agent

Documentation: `docs/FILE_AGENT_FA.md`.

**New files:** `kira/tools/fileagent.py`, `tests/test_file_agent.py` (10 tests), and the documentation.

**Changes:** `kira/tools/builtin.py` (registration), `kira/tools/protocol.py` (file-category gate words such as copy, rename, organize, and undo), and `kira/tools/agent.py` (labels).

**Intentionally not implemented:** Word/PDF support, UI control (T5-B onward), and permanent deletion (all deletion operations go to the Recycle Bin).

---

## v14 — T5-B: Desktop Interaction

Documentation: `docs/DESKTOP_FA.md`.

**New files:** `kira/tools/desktop.py`, `tests/test_desktop.py` (14 tests with a fake backend), and the documentation.

**Changes:** `wincontrol.py` (desktop domain), `builtin.py` (module registration), `protocol.py` (desktop category and `DESKTOP_RULES`), and `agent.py` (labels and rules).

**Intentionally not implemented:** Word/Office (T5-C), brightness/Wi-Fi (T5-D), screenshots and vision, Windows key, and system shortcuts.

**Historical validation note:** policy logic was tested, but Win32 calls and UI Automation scripts can run only on Windows and were not executed in that development environment.

---

## v12 — Persian application-name discovery and writing quality

**Change baseline:** the GitHub Release with tag `stage3-neon-glass-2026-11-11`. The change was developed on a separate branch; previous release files were not overwritten.

- `kira/tools/apps.py`: Persian command-phrase cleanup, common phonetic application aliases, and exclusion of broken shortcuts before building the launch catalog. An alternate executable path in the install folder remains subject to safety checks.
- `kira/tools/protocol.py` and `kira/tools/winmodules.py`: explicit instructions for invoking `open_app` with a Persian application name from the first request, without requiring an English name or triggering web search.
- `kira/personality.py`: a Persian spelling and half-space review contract that preserves conversational style.
- Gemini Model Discovery, Route/Cooldown/Failover, Agent Planner, memory, and Mood already existed in the baseline and were not rewritten to avoid duplicate work.
