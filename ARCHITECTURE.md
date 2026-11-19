# Kira Architecture

**Current architecture source:** [docs/ARCHITECTURE_MASTER.md](docs/ARCHITECTURE_MASTER.md)  
**Snapshot branch:** `new-main`  
**Last synchronized:** 2026-11-19

This file is the short repository-level entry point. It intentionally contains no independent architecture claims; the linked documents below are the canonical records.

## Canonical architecture documents

1. [Architecture Master](docs/ARCHITECTURE_MASTER.md) — verified current structure, runtime composition, dependency directions and subsystem boundaries.
2. [Module Ownership](docs/MODULE_OWNERSHIP.md) — module owners, public contracts, allowed dependencies and forbidden coupling.
3. [Architecture Roadmap](docs/ARCHITECTURE_ROADMAP.md) — confirmed technical debt, extraction decisions and ordered next steps.
4. [Architecture Implementation Handoff](docs/ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md) — implementation evidence and reviewer checklist for TASK 017–020.

## Current architecture facts

- Product entry point: `kira/main.py`.
- Production Qt Composition Root: `kira/ui/bootstrap.py`.
- Application services and feature factories are registered through `kira/app/feature_modules.py`.
- The production window is `kira/ui/main_window.py`, composed with eight window-scoped Feature Controllers and an explicit `FeatureControllerRegistry`.
- Chat domain/application services are under `kira/chat`, `kira/domain`, `kira/core/interfaces` and `kira/app`.
- The shared EventBus carries notifications; direct request/response work uses explicit service contracts.
- Durable Chat persistence is owned by the Chat persistence/repository boundary. Runtime Session state is separate from durable Conversation state.
- MainWindow is no longer the legacy monolith, but Qt presentation, worker/resource lifecycle and some UI orchestration remain in the UI layer.

## Verification policy

A source file, test, merged pull request or green workflow status alone does not prove runtime behavior. Report static inspection, test execution, CI runner execution and Windows desktop acceptance separately. A workflow job with no runner/steps is **not executed** and must never be reported as a passing test.

For current status and limitations, use the verification sections in the three canonical documents and the latest entry in [TASK_HANDOFF.md](TASK_HANDOFF.md). Historical migration notes belong in dated records under `docs/`, not in this entry point.
