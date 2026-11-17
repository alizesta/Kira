"""Versioned, Qt-free conversation export/import."""
from __future__ import annotations
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

SCHEMA_VERSION = 1
EXPORT_VERSION = "1.0"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CONVERSATIONS = 1_000
MAX_MESSAGES = 100_000
MAX_CONTENT_CHARS = 2_000_000
MAX_METADATA_DEPTH = 12
_SECRET_KEY = re.compile(r"(?:api.?key|access.?token|refresh.?token|token|password|passwd|secret|credential|authorization|cookie|private.?key)", re.I)
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ALLOWED_ROLES = {"user", "assistant", "system"}
_ALLOWED_STATUSES = {"streaming", "complete", "interrupted", "failed", "cancelled"}

class TransferError(ValueError):
    """Invalid transfer document or operation."""

class TransferRepository(Protocol):
    def list_conversations(self, character_id: str | None = None) -> list[dict[str, Any]]: ...
    def get_transfer_messages(self, conversation_id: str, character_id: str, after_created_at: str = "", after_id: int = 0, limit: int = 1000) -> list[dict[str, Any]]: ...
    def messages_after(self, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]: ...
    def import_transfer_records(self, conversations: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict[str, Any]: ...

@dataclass(frozen=True)
class ImportPreview:
    valid: bool
    conversation_count: int
    message_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ImportResult:
    imported_conversations: int
    imported_messages: int
    skipped_duplicates: int
    remapped_conversations: int
    remapped_messages: int
    conversation_id_map: Mapping[str, str]

def _sanitize_json(value: Any, depth: int = 0) -> Any:
    if depth > MAX_METADATA_DEPTH:
        raise TransferError("Metadata nesting exceeds the supported depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise TransferError("Non-finite metadata numbers are not supported")
        return value
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item, depth + 1) for item in value[:10000]]
    if isinstance(value, Mapping):
        return {str(key)[:256]: _sanitize_json(item, depth + 1)
                for key, item in value.items() if not _SECRET_KEY.search(str(key))}
    return None

def _json_bytes(source: Any) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif isinstance(source, Path):
        if not source.is_file(): raise TransferError("Import source is not a regular file")
        if source.stat().st_size > MAX_FILE_BYTES: raise TransferError("Import file exceeds 20 MiB")
        raw = source.read_bytes()
    elif isinstance(source, str):
        if source.lstrip().startswith("{"):
            raw = source.encode("utf-8")
        else:
            path = Path(source)
            if not path.is_file(): raise TransferError("Import source must be JSON text or an existing file")
            if path.stat().st_size > MAX_FILE_BYTES: raise TransferError("Import file exceeds 20 MiB")
            raw = path.read_bytes()
    else:
        raise TransferError("Import source must be a path, bytes, JSON text or object")
    if len(raw) > MAX_FILE_BYTES: raise TransferError("Import file exceeds 20 MiB")
    return raw

def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise TransferError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result

class ChatTransfer:
    """Transfer service composed with the injected ChatPersistence repository port."""
    def __init__(self, repository: TransferRepository):
        if repository is None: raise TypeError("repository is required")
        self._repository = repository

    @staticmethod
    def _selected_ids(conversation_ids):
        if conversation_ids is None: return None
        values = tuple(dict.fromkeys(str(value).strip() for value in conversation_ids))
        if not values or any(not value for value in values):
            raise TransferError("At least one non-empty conversation ID is required")
        return set(values)

    def export_data(self, conversation_ids=None, *, character_id: str | None = None) -> dict[str, Any]:
        selected = self._selected_ids(conversation_ids)
        source = self._repository.list_conversations(character_id)
        if selected is not None:
            source = [row for row in source if str(row.get("id")) in selected]
            missing = selected - {str(row.get("id")) for row in source}
            if missing: raise TransferError("Unknown conversation ID(s): " + ", ".join(sorted(missing)))
        if len(source) > MAX_CONVERSATIONS: raise TransferError("Conversation count exceeds 1,000")
        output, total = [], 0
        for conv in source:
            conv_id = str(conv.get("id") or "")
            if not conv_id: raise TransferError("Persistence returned a conversation without an ID")
            character = str(conv.get("character_id") or "kira")
            exported_messages = []
            cursor_stamp, cursor_id = "", 0
            while True:
                batch = self._repository.get_transfer_messages(
                    conv_id, character, cursor_stamp, cursor_id, limit=1000
                )
                if not batch:
                    break
                for msg in batch:
                    total += 1
                    if total > MAX_MESSAGES: raise TransferError("Message count exceeds 100,000")
                    content = str(msg["content"])
                    if len(content) > MAX_CONTENT_CHARS: raise TransferError("A message exceeds the 2,000,000 character limit")
                    record = {
                        "id": int(msg["id"]), "role": str(msg["role"]), "content": content,
                        "created_at": str(msg.get("created_at") or ""), "character_id": str(msg.get("character_id") or character),
                        "conversation_id": conv_id, "metadata": _sanitize_json(msg.get("metadata") or {}),
                        "status": str(msg.get("status") or "complete"),
                    }
                    exported_messages.append(record)
                    cursor_stamp, cursor_id = record["created_at"], record["id"]
                    if len(json.dumps(record, ensure_ascii=False, separators=(",", ":" )).encode("utf-8")) + 4096 > MAX_FILE_BYTES:
                        raise TransferError("Generated export exceeds 20 MiB")
                if len(batch) < 1000:
                    break
            conversation_record = {
                "id": conv_id, "character_id": character,
                "title": str(conv.get("title") or ""), "metadata": _sanitize_json(conv.get("metadata") or {}),
                "status": str(conv.get("status") or "active"), "created_at": str(conv.get("created_at") or ""),
                "updated_at": str(conv.get("updated_at") or ""), "messages": exported_messages,
            }
            output.append(conversation_record)
            estimated = len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if estimated > MAX_FILE_BYTES: raise TransferError("Generated export exceeds 20 MiB")
        return {"schema_version": SCHEMA_VERSION, "export_version": EXPORT_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "conversations": output}

    def export_json(self, conversation_ids=None, *, character_id: str | None = None) -> str:
        value = json.dumps(self.export_data(conversation_ids, character_id=character_id), ensure_ascii=False, indent=2, allow_nan=False)
        if len(value.encode("utf-8")) > MAX_FILE_BYTES: raise TransferError("Generated export exceeds 20 MiB")
        return value

    def write_export(self, directory: str | Path, *, filename="kira-chat-export.json", conversation_ids=None, character_id=None) -> Path:
        if not _SAFE_FILENAME.fullmatch(filename) or filename in {".", ".."} or not filename.lower().endswith(".json"):
            raise TransferError("Filename must be a simple basename without path components")
        root = Path(directory).resolve()
        if not root.is_dir(): raise TransferError("Export directory must already exist")
        destination = root / filename
        fd, temporary = tempfile.mkstemp(prefix=".kira-export-", suffix=".tmp", dir=str(root))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self.export_json(conversation_ids, character_id=character_id).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except Exception:
            try: os.unlink(temporary)
            except OSError: pass
            raise
        return destination

    def _parse(self, source):
        try:
            if isinstance(source, Mapping):
                raw = json.dumps(source, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if len(raw) > MAX_FILE_BYTES:
                    raise TransferError("Import document exceeds 20 MiB")
            else:
                raw = _json_bytes(source)
            document = json.loads(raw.decode("utf-8-sig"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(TransferError(f"Invalid JSON number: {value}")))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
            if isinstance(exc, TransferError):
                raise
            raise TransferError(f"Invalid UTF-8 JSON document: {exc}") from exc
        if not isinstance(document, dict): raise TransferError("Export root must be an object")
        if type(document.get("schema_version")) is not int or document["schema_version"] != SCHEMA_VERSION:
            raise TransferError(f"Unsupported schema_version: {document.get('schema_version')!r}")
        if document.get("export_version") != EXPORT_VERSION: raise TransferError("Unsupported export_version")
        if not isinstance(document.get("exported_at"), str) or len(document["exported_at"]) > 64:
            raise TransferError("exported_at must be a bounded timestamp string")
        try:
            datetime.fromisoformat(document["exported_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise TransferError("exported_at must be an ISO-8601 timestamp") from exc
        raw_convs = document.get("conversations")
        if not isinstance(raw_convs, list) or len(raw_convs) > MAX_CONVERSATIONS:
            raise TransferError("conversations must be an array within the 1,000 item limit")
        conversations, messages, seen, seen_message_ids = [], [], set(), set()
        for ci, conv in enumerate(raw_convs):
            if not isinstance(conv, dict): raise TransferError(f"conversations[{ci}] must be an object")
            conv_id, char_id = conv.get("id"), conv.get("character_id")
            if not isinstance(conv_id, str) or not conv_id.strip() or len(conv_id) > 256:
                raise TransferError(f"conversations[{ci}].id is invalid")
            if conv_id in seen: raise TransferError(f"Duplicate conversation ID: {conv_id}")
            seen.add(conv_id)
            if not isinstance(char_id, str) or not char_id.strip() or len(char_id) > 128:
                raise TransferError(f"conversations[{ci}].character_id is invalid")
            status = conv.get("status", "active")
            if not isinstance(status, str) or status not in {"active", "closed", "archived"}: raise TransferError(f"conversations[{ci}].status is invalid")
            raw_msgs = conv.get("messages")
            if not isinstance(raw_msgs, list): raise TransferError(f"conversations[{ci}].messages must be an array")
            conversations.append({
                "id": conv_id, "character_id": char_id.strip().lower(),
                "title": str(conv.get("title") or "")[:10000], "metadata": _sanitize_json(conv.get("metadata") or {}),
                "status": status, "created_at": str(conv.get("created_at") or "")[:64],
                "updated_at": str(conv.get("updated_at") or conv.get("created_at") or "")[:64],
            })
            for mi, msg in enumerate(raw_msgs):
                if len(messages) >= MAX_MESSAGES: raise TransferError("Message count exceeds 100,000")
                if not isinstance(msg, dict): raise TransferError(f"conversations[{ci}].messages[{mi}] must be an object")
                mid, role, content = msg.get("id"), msg.get("role"), msg.get("content")
                if type(mid) is not int or mid < 1: raise TransferError(f"conversations[{ci}].messages[{mi}].id must be positive integer")
                if mid in seen_message_ids: raise TransferError(f"Duplicate message ID in export: {mid}")
                seen_message_ids.add(mid)
                if not isinstance(role, str) or role not in _ALLOWED_ROLES or not isinstance(content, str) or len(content) > MAX_CONTENT_CHARS:
                    raise TransferError(f"conversations[{ci}].messages[{mi}] has invalid role/content")
                msg_status = msg.get("status", "complete")
                if not isinstance(msg_status, str) or msg_status not in _ALLOWED_STATUSES: raise TransferError(f"conversations[{ci}].messages[{mi}].status is invalid")
                if msg.get("conversation_id", conv_id) != conv_id: raise TransferError("Message conversation reference mismatch")
                supplied_character = msg.get("character_id", char_id)
                if not isinstance(supplied_character, str) or supplied_character.strip().lower() != char_id.strip().lower():
                    raise TransferError("Message character reference mismatch")
                messages.append({
                    "id": mid, "role": role, "content": content, "created_at": str(msg.get("created_at") or "")[:64],
                    "character_id": char_id.strip().lower(), "conversation_id": conv_id,
                    "metadata": _sanitize_json(msg.get("metadata") or {}), "status": msg_status,
                })
        return conversations, messages

    def preview_import(self, source) -> ImportPreview:
        try:
            convs, messages = self._parse(source)
            existing = {str(row.get("id")): str(row.get("character_id") or "kira")
                        for row in self._repository.list_conversations()}
            warnings = []
            # Message IDs are global primary keys, not scoped to a conversation.
            # Page the complete ID space so preview catches collisions even when
            # the conflicting row belongs to an unrelated conversation/character.
            global_message_ids = set()
            cursor_id = 0
            while True:
                batch = self._repository.messages_after(cursor_id, limit=5000)
                if not batch:
                    break
                for row in batch:
                    global_message_ids.add(int(row["id"]))
                cursor_id = int(batch[-1]["id"])
                if len(batch) < 5000:
                    break

            existing_ids = {}
            existing_signatures = {}
            for conv in convs:
                current_character = existing.get(conv["id"])
                if current_character is None:
                    continue
                if current_character.lower() != conv["character_id"].lower():
                    warnings.append(f"Conversation {conv['id']} will receive a new ID because it belongs to another character.")
                    continue
                ids, signatures = set(), set()
                stamp, message_id = "", 0
                while True:
                    batch = self._repository.get_transfer_messages(
                        conv["id"], conv["character_id"], stamp, message_id, limit=1000
                    )
                    if not batch:
                        break
                    for row in batch:
                        ids.add(int(row["id"]))
                        signatures.add((
                            str(row["role"]), str(row["content"]), str(row.get("created_at") or ""),
                            str(row.get("character_id") or conv["character_id"]).lower(), conv["id"],
                            json.dumps(_sanitize_json(row.get("metadata") or {}), ensure_ascii=False, sort_keys=True),
                            str(row.get("status") or "complete"),
                        ))
                    stamp = str(batch[-1].get("created_at") or "")
                    message_id = int(batch[-1]["id"])
                    if len(batch) < 1000:
                        break
                existing_ids[conv["id"]] = ids
                existing_signatures[conv["id"]] = signatures
            duplicate_count = 0
            collision_conversations = set()
            for message in messages:
                conv_id = message["conversation_id"]
                if conv_id not in existing_ids:
                    if message["id"] in global_message_ids:
                        collision_conversations.add(conv_id)
                    continue
                signature = (
                    message["role"], message["content"], message["created_at"],
                    message["character_id"], conv_id,
                    json.dumps(message["metadata"], ensure_ascii=False, sort_keys=True), message["status"],
                )
                if signature in existing_signatures[conv_id]:
                    duplicate_count += 1
                elif message["id"] in global_message_ids:
                    collision_conversations.add(conv_id)
            if duplicate_count:
                warnings.append(f"{duplicate_count} identical message(s) will be skipped.")
            if collision_conversations:
                warnings.append(
                    f"{len(collision_conversations)} conversation(s) contain message ID collisions; "
                    "their imported message IDs will be reassigned together to preserve ordering."
                )
            return ImportPreview(True, len(convs), len(messages), (), tuple(warnings))
        except (TransferError, OSError, TypeError, ValueError, RecursionError) as exc:
            return ImportPreview(False, 0, 0, (str(exc),))

    def import_data(self, source) -> ImportResult:
        convs, messages = self._parse(source)
        result = self._repository.import_transfer_records(convs, messages)
        return ImportResult(int(result["imported_conversations"]), int(result["imported_messages"]),
            int(result["skipped_duplicates"]), int(result["remapped_conversations"]),
            int(result["remapped_messages"]), dict(result["conversation_id_map"]))
