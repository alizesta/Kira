# TASK 001–015 Regression Campaign

**Repository:** `alizesta/Kira`  
**Target:** `new-main`  
**Base SHA at campaign start:** `b54d092a330b6383ca4244320ffaeec9267db561`  
**Campaign branch:** `qa/audit-tasks-001-015`

## Scope

This campaign checks the merged implementation for TASK 001–014 and the architecture claims recorded by TASK 015. TASK 016 remains in its own PR/branch and is deliberately outside this change set.

The Windows workflow uses full `unittest discover` across the repository. The portable workflow is expanded to include the chat architecture boundary, lifecycle, organization, search and transfer suites that were not previously in its explicit regression command.

## Coverage added or restored

- `tests/test_app_architecture.py` — application boundary and shared EventBus.
- `tests/test_chat_conversation_lifecycle.py` — archive, restore, soft delete, group atomicity and permanent-delete authorization.
- `tests/test_chat_organization.py` — character ownership, metadata preservation, tag/folder operations, filters, events and validation.
- `tests/test_chat_search.py` — lifecycle status filtering and repository contract errors.
- `tests/test_chat_transfer.py` — global message-ID collision preview and `trashed` status acceptance.
- `tests/test_chat_persistence_contract.py` — atomic lifecycle batch rollback, message preservation, expected-status guard and foreign-key dependency refusal.

The Lifecycle tests were converted from pytest to unittest because the Windows full-suite job uses `python -m unittest discover` and does not install pytest.

## Static findings fixed

- Organization labels now reject control characters before whitespace normalization.
- Organization metadata rejects NaN and infinite floating-point values, keeping stored metadata JSON-compatible.
- Optional organization descriptions can be cleared using an empty value.

## Validation status

Pending GitHub Actions execution for this campaign PR. No local checkout is available in the execution environment; no local test result is claimed. Results, job IDs, exact commit SHA and any remaining debt will be recorded here after CI finishes.

## Known architecture debt retained

- TASK 015's audit notes that `kira/oldmain.py` / MainWindow still owns application policy beyond the target thin-shell architecture. This is a migration item, not a regression to expand during this test campaign.
- TASK 014 documents that bulk organization tag/folder changes are currently per-conversation operations, not one cross-conversation transaction. This campaign checks current behavior; it does not silently claim atomic bulk organization updates.
- GUI behaviour and actual Windows desktop interaction still require the Windows/offscreen suite and, where applicable, manual Windows 11 smoke checks.
