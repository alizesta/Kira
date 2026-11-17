# Chat Attachments & Content Processing

## Ownership and boundaries

`kira.chat.attachments` is the framework-independent attachment boundary. It owns managed temporary copies, validation, session scoping, metadata, content extraction and cleanup. It has no PySide6, Widget, MainWindow, Provider, Prompt, or Persistence dependency.

`kira/chat/attachment_content.py` owns the pure, bounded parsers for the supported formats (text, PDF, DOCX and ZIP) and image payload conversion. It has no Qt or legacy-module dependency. `kira.attachments` is now a compatibility facade that re-exports this parser API; it is not a second parser implementation. `kira.chat.attachments` composes that parser with session-scoped managed storage and also exposes the compatibility functions used by the existing asynchronous UI worker.

## Public contract

- `Attachment`: immutable record containing `attachment_id`, optional `message_id`, `session_id`, `filename`, `mime_type`, `size`, `source`, managed `path`, `metadata`, and `status`.
- `AttachmentManager.add_attachment(source, filename, session_id, message_id=None, metadata=None)`: copies a file or bytes into a unique session-owned path.
- `validate_attachment(filename, data)`: checks extension allowlist, size, and file signatures / content.
- `get_attachment(id, session_id)` and `list_attachments(session_id, message_id=None)`: scoped lookup. The session identifier is required for every direct lookup.
- `prepare_content(ids, session_id, text="", search=False)`: extracts supported content and returns structured `text`, `files`, and `images` data plus UI/history `display` and `stored` fields, bounded `errors`, and `prepared_count`. It does not build provider prompt text.
- `remove_attachment(id, session_id)` and `cleanup(session_id=None)`: remove only files under the manager's resolved storage root and owning session directory.
- `close()`: idempotent cleanup; an internally-created temporary root is removed.

## Supported formats and limits

This task preserves the existing parser's supported formats; it does not introduce new media formats.

- Images: PNG, JPEG, WEBP, GIF and BMP. Default input limit: 15 MiB.
- Documents/archives: PDF, DOCX and ZIP. Default input limit: 50 MiB.
- Text/source files: the existing allowlist of plain-text, configuration, data and source-code extensions. Default input limit: 50 MiB.
- ZIP extraction remains bounded by explicit archive-entry, per-member and expanded-size limits. Archives are inspected in place and are not extracted to arbitrary paths.
- Audio/video are not newly enabled: the current chat attachment parser does not decode or forward them.

The manager checks both the extension allowlist and file signatures. MIME metadata is derived from the validated content rather than trusted from the caller. Text is rejected when its content is binary or inconsistent with the text contract.

## Lifecycle and isolation

Files are copied into a private manager root and then into a directory derived from a one-way hash of the session identifier. Stored filenames use generated attachment IDs; user-provided names are metadata only. Identical content can be reused within the same session/message scope. Removal verifies both the session directory and manager root before unlinking. A lookup, preparation or removal request for another session is rejected.

A manager created without an explicit root owns a private temporary directory and removes it on `close()`. A manager given a root cleans managed files but leaves ownership of that root to its caller. Callers should close the manager when the owning chat application/service shuts down.

## Integration responsibilities

- UI: choose local files, display progress and status, and pass selected content through the chat attachment boundary.
- Chat Application Service: owns/injects the manager, stores the existing UI payloads under the active request ID (used as the request-scoped message key), exposes add/prepare/remove/cleanup methods, and removes temporary copies when the request completes, is cancelled, or its session closes.
- Context Builder: receives structured `text` / `files` / `images` data and composes the provider-facing user message. This is the only layer that combines extracted file text and image markers with the message prompt.
- Provider: receive already-prepared image/text content; it does not manage local files.
- Persistence: continue owning durable message/history records. The temporary manager is not a second history database.

The parser compatibility API is retained so current image paste, screen capture, game-vision and upload flows are not broken. Both `kira.chat.attachments` and the legacy `kira.attachments` import resolve to the single parser implementation in `kira.chat.attachment_content`; selected payloads are copied into managed storage by ChatApplicationService. The manager does not import or delegate to the legacy module.


## Current request pipeline

1. The UI attachment controller keeps selection, progress and preview responsibilities and supplies the existing image/text payload format.
2. ChatApplicationService validates that payload and registers each file under the current session and request-scoped message key.
3. AttachmentManager extracts file content into structured records. A single failed file is reported without discarding successfully prepared siblings.
4. ContextBuilder combines the original user text, extracted file text and image references into the provider-facing user message. AttachmentManager never creates a Provider prompt.
5. ChatApplicationService removes the managed temporary copies when the corresponding request reaches a terminal state. A session close also cleans any remaining files for that session.
