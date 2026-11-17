# Chat Transfer — TASK 012

## Ownership

`kira/chat/transfer.py` owns JSON serialization, schema validation, secret-metadata filtering, import preview and orchestration. It is Qt-free and receives a `TransferRepository` port by constructor injection.

`ChatPersistence` / `SqliteChatRepository` remain the sole owners of durable storage and SQL transactions. The repository's `import_transfer_records` operation commits all imported conversations and messages in one database transaction. Transfer never opens a database or changes the active runtime Session.

## JSON contract

UTF-8 JSON uses `schema_version: 1`, `export_version: "1.0"`, UTC `exported_at`, and `conversations[]`. Each conversation carries its durable ID, character, title, status, timestamps, metadata and ordered `messages[]`. Messages retain integer IDs, role, content, timestamp, character/conversation IDs, metadata and lifecycle status. Ordering is `(created_at, id)`. Schema evolution requires an explicit parser/migration path; unknown versions are rejected.

## Import policy

- The entire document is size-bounded and validated before repository writes.
- JSON only: no pickle, object hooks, executable payloads or embedded file paths.
- Duplicate object keys, malformed records, unsupported roles/statuses, mismatched references and duplicate conversation IDs reject the document.
- Same-ID/same-character conversations are reused without overwriting existing metadata. A conversation ID owned by another character is remapped to a new UUID.
- Free message IDs are preserved when possible. If one non-duplicate ID collision occurs in a conversation, that conversation’s imported message IDs are allocated together to preserve equal-timestamp ordering; identical message fingerprints are skipped.
- All durable inserts run in one repository transaction and roll back on failure.
- `preview_import` validates/counts without writing; `import_data` validates again before commit.

## Security limits

- 20 MiB maximum file; 1,000 conversations; 100,000 messages; 2,000,000 characters per message; metadata depth 12.
- Sensitive metadata keys matching API keys, tokens, passwords, secrets, credentials, authorization, cookies or private keys are recursively removed.
- Export filenames are safe basenames only. Writes use a temporary file in the selected directory and atomic replacement.
- Import never accepts paths from the document and cannot alter provider configuration or runtime Session state.

## Composition

Construct `ChatTransfer(chat_persistence)`; the injected object must implement `list_conversations`, `get_messages` and `import_transfer_records`. The latter is exposed by the `ChatPersistence` facade and implemented by its repository.
