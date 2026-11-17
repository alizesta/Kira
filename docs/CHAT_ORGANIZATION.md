# Chat Conversation Metadata & Organization (TASK 014)

## Ownership

`kira/chat/organization.py` owns conversation titles, tags, folder assignment, favorite state, category, color, description, manual display order and organization filters. It is framework-independent and has no Qt, MainWindow, widget, SQL or Session dependency.

The service receives the existing `ChatPersistence` facade through the `OrganizationRepository` protocol. Persistence remains the sole owner of durable storage and transaction/schema behavior. No second database or cache is created.

## Metadata format and compatibility

All organization-owned fields live below the conversation-level metadata key `organization`. Existing top-level metadata keys and unknown nested values are preserved when the organization namespace is updated. Existing conversations without this key resolve to the default `inbox` folder, have no tags and are not favorited. Message content and message metadata are never modified.

The namespace supports `title_source` (`manual` or `automatic`), `tags`, `folder_id`, `favorite`, `category`, `color`, `description`, `order`, and additional bounded JSON-compatible keys.

Tags and folders are value-based, not separately catalogued entities. A tag or folder becomes durable when referenced by a conversation; unused empty definitions are descriptors only. Deleting a tag removes matching assignments. Deleting a folder moves its conversations to `inbox`. The default folder cannot be deleted. This avoids a parallel taxonomy database and allows future nested folder paths.

## API

- `ChatOrganizationService(repository, character_id=None, event_publisher=None)`
- `rename_conversation(id, title, automatic=False)`
- `create_tag(name)`, `delete_tag(tag_id)`, `add_tag(id, tag)`, `remove_tag(id, tag)`
- `create_folder(name)`, `delete_folder(folder_id)`, `move_conversation(id, folder_id)`
- `set_favorite(id, bool)`, `update_metadata(id, mapping)`, `get_organization(id)`
- `filter_conversations(OrganizationFilter(...))`

Filters combine by AND and return copied records; they never mutate source data. Supported sort keys are title, creation time, last activity and manual order. Structured domain and repository errors distinguish invalid input from persistence failures. Optional typed event publishing is best-effort after persistence.

## Adjacent module boundaries

- TASK 005 remains the only durable storage owner; organization calls its injected conversation metadata API and does not open SQLite.
- TASK 007 remains the owner of runtime Session identity and state.
- TASK 008 shared Chat Events is used for metadata change notifications.
- TASK 011 remains the owner of message text search/retrieval. Organization filters operate on conversation records and do not perform message matching.
- TASK 012 already exports/imports the complete conversation metadata object; the namespaced organization payload is preserved without changing the transfer schema.
- TASK 013 remains the owner of archive/restore/delete lifecycle. This service never changes conversation status or deletes conversations.
- TASK 006 coordinates calls; TASK 010 may invoke the public API but owns no organization rules.

## Known limitations

The existing persistence facade exposes whole-document conversation metadata updates rather than an atomic JSON-path patch. The service serializes its own in-process mutations, but independent writers can still race when updating the same conversation metadata. Empty folder/tag definitions are not persisted until assigned to a conversation. Delete-tag/delete-folder perform per-conversation updates rather than a cross-conversation transaction; a repository-level bulk operation is required for atomicity.
