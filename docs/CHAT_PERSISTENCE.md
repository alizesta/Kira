# Chat SQLite persistence policy

## Contracts and ownership

`ChatPersistence` remains the application-facing facade. The repository
contract is split into conversation, message and history-maintenance
capabilities in `repository_contracts.py`; the SQLite repository retains its
existing public API.

`SqliteConnectionManager` owns normal database connections. Every operation
uses a `SqliteUnitOfWork`: successful scopes commit, exceptional scopes roll
back, and every scope closes its connection. Conversation/message CRUD remains
in the compatibility repository; crash recovery, snapshots and the durable
pending queue have independent owners.

## SQLite policy

- Journal mode: WAL, enabled and verified during initialization.
- Synchronous mode: FULL on every normal connection.
- Busy timeout: 250 ms; interactive operations do not wait indefinitely.
- Foreign keys: enabled on every normal connection.
- WAL autocheckpoint: 1000 pages.
- Read-only integrity/recovery connections do not mutate journal settings.

If the configured filesystem cannot enable WAL, initialization reports a
storage failure instead of silently downgrading the durability policy.

## Versioned migrations

Schema version 1 contains the existing conversation/message schema and
legacy conversation backfill. Version 2 adds `persistence_receipts`, whose
unique token makes replay idempotent if the process stops after the message
transaction commits but before the JSONL spool is removed. Migration DDL,
version records and data backfill execute inside the caller's transaction.
Existing databases receive an online SQLite backup before migration; newer
schema versions are rejected without downgrade.

## Crash and recovery

The emergency queue appends JSONL records, flushes and fsyncs the file. Replay
inserts a receipt and its message in one transaction. A failed Unit of Work
rolls back all its writes. Recovery runs `PRAGMA quick_check`, preserves an
unhealthy database and sidecars under a quarantine name, salvages readable
messages, and merges them with the newest healthy backup. Snapshots use
SQLite's online backup API, including committed WAL content.
