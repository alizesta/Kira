# Kira Architecture

**Current architecture source:** [Architecture Master](ARCHITECTURE_MASTER.md)

This is the English short entry point for the architecture documentation. It does not introduce independent architecture claims; the linked documents are the canonical records.

## Canonical architecture documents

1. [Architecture Master](ARCHITECTURE_MASTER.md) — verified current structure, runtime composition, dependency directions, and subsystem boundaries.
2. [Module Ownership](MODULE_OWNERSHIP.md) — module ownership, public contracts, allowed dependencies, and forbidden coupling.
3. [Architecture Roadmap](ARCHITECTURE_ROADMAP.md) — confirmed technical debt, extraction decisions, and ordered engineering work.
4. [Architecture Implementation Handoff](ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md) — implementation evidence and reviewer checklist.

## Synchronization principle

Architecture documentation must remain aligned with the working branch. A description in a document does not by itself prove that the code has run or passed real-world acceptance. Automated tests, Windows GUI execution, audio hardware, and performance checks must be verified separately.
