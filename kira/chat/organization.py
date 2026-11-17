"""Qt-free conversation metadata and organization service."""
from __future__ import annotations
import copy
import math
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

ORGANIZATION_KEY = "organization"
DEFAULT_FOLDER_ID = "inbox"
MAX_TITLE_LENGTH = 120
MAX_LABEL_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 500
MAX_METADATA_DEPTH = 8
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class OrganizationError(ValueError):
    """Invalid organization operation or conversation reference."""


class OrganizationRepositoryError(RuntimeError):
    """The injected persistence boundary failed."""


class OrganizationRepository(Protocol):
    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...
    def list_conversations(self, character_id: str | None = None) -> list[dict[str, Any]]: ...
    def update_conversation(self, conversation_id: str, **changes: Any) -> bool: ...


@dataclass(frozen=True)
class OrganizationResult:
    success: bool
    conversation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    value: Any = None
    error: str | None = None


@dataclass(frozen=True)
class OrganizationFilter:
    folder_id: str | None = None
    tags: tuple[str, ...] = ()
    favorite: bool | None = None
    category: str | None = None
    query: str | None = None
    sort_by: str = "updated"
    descending: bool = True


@dataclass(frozen=True)
class Tag:
    id: str
    name: str


@dataclass(frozen=True)
class Folder:
    id: str
    name: str


def _label(value: Any, field_name: str, maximum: int = MAX_LABEL_LENGTH) -> str:
    if not isinstance(value, str):
        raise OrganizationError(f"{field_name} must be text")
    if _CONTROL.search(value):
        raise OrganizationError(f"{field_name} must contain 1 to {maximum} printable characters")
    normalized = unicodedata.normalize("NFKC", _SPACE.sub(" ", value)).strip()
    if not normalized or len(normalized) > maximum or _CONTROL.search(normalized):
        raise OrganizationError(f"{field_name} must contain 1 to {maximum} printable characters")
    return normalized


def _key(value: Any, field_name: str) -> str:
    return _label(value, field_name).casefold()


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > MAX_METADATA_DEPTH:
        raise OrganizationError("metadata nesting exceeds the supported depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise OrganizationError("metadata numbers must be finite")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise OrganizationError("metadata keys must be bounded strings")
            result[key] = _safe_value(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 1000:
            raise OrganizationError("metadata arrays are limited to 1,000 items")
        return [_safe_value(item, depth + 1) for item in value]
    raise OrganizationError(f"unsupported metadata value: {type(value).__name__}")


def _organization(metadata: Any) -> dict[str, Any]:
    source = copy.deepcopy(dict(metadata)) if isinstance(metadata, Mapping) else {}
    value = source.get(ORGANIZATION_KEY)
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


class ChatOrganizationService:
    """Owns organization metadata only; lifecycle and message data remain external."""

    def __init__(self, repository: OrganizationRepository, *, character_id: str | None = None,
                 event_publisher: Any | None = None) -> None:
        if repository is None:
            raise TypeError("repository is required")
        self._repository = repository
        self._character_id = str(character_id).strip().lower() if character_id else None
        self._events = event_publisher
        self._lock = threading.RLock()
        self._known_folders = {DEFAULT_FOLDER_ID: "Inbox"}

    def _conversation(self, conversation_id: Any) -> dict[str, Any]:
        identifier = str(conversation_id or "").strip()
        if not identifier or len(identifier) > 256:
            raise OrganizationError("conversation_id is invalid")
        try:
            record = self._repository.get_conversation(identifier)
        except Exception as exc:
            raise OrganizationRepositoryError(str(exc)) from exc
        if not isinstance(record, dict) or str(record.get("id") or "") != identifier:
            raise OrganizationError("conversation does not exist")
        owner = str(record.get("character_id") or "").strip().lower()
        if self._character_id and owner != self._character_id:
            raise OrganizationError("conversation is outside the active character scope")
        return record

    def _publish(self, record: Mapping[str, Any], organization: Mapping[str, Any]) -> None:
        publish = getattr(self._events, "publish", None)
        if not callable(publish):
            return
        try:
            publish("conversation_metadata_updated", payload={
                "conversation_id": str(record.get("id") or ""),
                "character_id": str(record.get("character_id") or ""),
                "organization": copy.deepcopy(dict(organization)),
            })
        except Exception:
            return

    def _save(self, record: dict[str, Any], organization: Mapping[str, Any]) -> OrganizationResult:
        metadata = copy.deepcopy(record.get("metadata")) if isinstance(record.get("metadata"), dict) else {}
        metadata[ORGANIZATION_KEY] = _safe_value(organization)
        try:
            if not self._repository.update_conversation(str(record["id"]), metadata=metadata):
                raise OrganizationRepositoryError("persistence did not update the conversation")
            updated = self._conversation(record["id"])
        except OrganizationRepositoryError:
            raise
        except Exception as exc:
            raise OrganizationRepositoryError(str(exc)) from exc
        current = _organization(updated.get("metadata"))
        self._publish(updated, current)
        return OrganizationResult(True, str(record["id"]), current)

    def rename_conversation(self, conversation_id: str, title: str, *, automatic: bool = False) -> OrganizationResult:
        normalized = _label(title, "title", MAX_TITLE_LENGTH)
        with self._lock:
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            if automatic and (org.get("title_source") == "manual" or
                              (str(record.get("title") or "").strip() and org.get("title_source") != "automatic")):
                return OrganizationResult(True, str(record["id"]), org, value="manual-title-preserved")
            org["title_source"] = "automatic" if automatic else "manual"
            metadata = copy.deepcopy(record.get("metadata")) if isinstance(record.get("metadata"), dict) else {}
            metadata[ORGANIZATION_KEY] = org
            try:
                if not self._repository.update_conversation(str(record["id"]), title=normalized, metadata=metadata):
                    raise OrganizationRepositoryError("persistence did not update the conversation")
                updated = self._conversation(record["id"])
            except OrganizationRepositoryError:
                raise
            except Exception as exc:
                raise OrganizationRepositoryError(str(exc)) from exc
            self._publish(updated, org)
            return OrganizationResult(True, str(record["id"]), org, value=normalized)

    def create_tag(self, name: str) -> Tag:
        normalized = _label(name, "tag name")
        return Tag(normalized.casefold(), normalized)

    def delete_tag(self, tag_id: str) -> int:
        key = _key(tag_id, "tag id")
        return self._update_all(lambda org: org.update(tags=[
            value for value in org.get("tags", []) if _key(value, "tag") != key
        ]))

    def add_tag(self, conversation_id: str, tag: str) -> OrganizationResult:
        value = _label(tag, "tag")
        with self._lock:
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            tags = list(org.get("tags") or [])
            if not any(_key(item, "tag") == _key(value, "tag") for item in tags):
                tags.append(value)
            org["tags"] = tags
            return self._save(record, org)

    def remove_tag(self, conversation_id: str, tag: str) -> OrganizationResult:
        key = _key(tag, "tag")
        with self._lock:
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            org["tags"] = [value for value in org.get("tags", []) if _key(value, "tag") != key]
            return self._save(record, org)

    def create_folder(self, name: str) -> Folder:
        normalized = _label(name, "folder name")
        folder_id = normalized.casefold()
        with self._lock:
            self._known_folders[folder_id] = normalized
        return Folder(folder_id, normalized)

    def delete_folder(self, folder_id: str) -> int:
        key = _key(folder_id, "folder id")
        if key == DEFAULT_FOLDER_ID:
            raise OrganizationError("the default folder cannot be deleted")
        def reset(org):
            if _key(org.get("folder_id") or DEFAULT_FOLDER_ID, "folder") == key:
                org["folder_id"] = DEFAULT_FOLDER_ID
        changed = self._update_all(reset)
        with self._lock:
            self._known_folders.pop(key, None)
        return changed

    def _folder_exists(self, folder_id: str) -> bool:
        if folder_id in self._known_folders:
            return True
        try:
            records = self._repository.list_conversations(self._character_id)
        except Exception as exc:
            raise OrganizationRepositoryError(str(exc)) from exc
        for record in records:
            org = _organization(record.get("metadata")) if isinstance(record, dict) else {}
            if _key(org.get("folder_id") or DEFAULT_FOLDER_ID, "folder") == folder_id:
                return True
        return False

    def move_conversation(self, conversation_id: str, folder_id: str) -> OrganizationResult:
        folder = _key(folder_id, "folder id")
        with self._lock:
            if not self._folder_exists(folder):
                raise OrganizationError("folder does not exist; create it before moving a conversation")
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            org["folder_id"] = folder or DEFAULT_FOLDER_ID
            return self._save(record, org)

    def set_favorite(self, conversation_id: str, favorite: bool) -> OrganizationResult:
        if not isinstance(favorite, bool):
            raise OrganizationError("favorite must be boolean")
        with self._lock:
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            org["favorite"] = favorite
            return self._save(record, org)

    def update_metadata(self, conversation_id: str, changes: Mapping[str, Any]) -> OrganizationResult:
        if not isinstance(changes, Mapping):
            raise OrganizationError("metadata changes must be a mapping")
        safe = _safe_value(changes)
        if {"tags", "folder_id", "favorite", "title_source"}.intersection(safe):
            raise OrganizationError("use the dedicated organization operation for reserved fields")
        with self._lock:
            record = self._conversation(conversation_id)
            org = _organization(record.get("metadata"))
            org.update(safe)
            if "color" in org and org["color"] is not None:
                color = str(org["color"]).strip()
                if len(color) > 32 or _CONTROL.search(color):
                    raise OrganizationError("color must be a short color token")
                org["color"] = color
            if "description" in org:
                org["description"] = _label(org["description"], "description", MAX_DESCRIPTION_LENGTH)
            if "order" in org:
                try:
                    org["order"] = int(org["order"])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise OrganizationError("order must be an integer") from exc
            return self._save(record, org)

    def get_organization(self, conversation_id: str) -> OrganizationResult:
        record = self._conversation(conversation_id)
        org = _organization(record.get("metadata"))
        org.setdefault("tags", [])
        org.setdefault("folder_id", DEFAULT_FOLDER_ID)
        org.setdefault("favorite", False)
        return OrganizationResult(True, str(record["id"]), org, value={
            "title": str(record.get("title") or ""),
            "created_at": str(record.get("created_at") or ""),
            "updated_at": str(record.get("updated_at") or ""),
        })

    def _update_all(self, mutation) -> int:
        try:
            records = self._repository.list_conversations(self._character_id)
        except Exception as exc:
            raise OrganizationRepositoryError(str(exc)) from exc
        changed = 0
        for record in records:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            with self._lock:
                current = self._conversation(record["id"])
                org = _organization(current.get("metadata"))
                before = copy.deepcopy(org)
                mutation(org)
                if org != before:
                    self._save(current, org)
                    changed += 1
        return changed

    def filter_conversations(self, filters: OrganizationFilter | None = None, **options: Any) -> list[dict[str, Any]]:
        if filters is not None and options:
            raise OrganizationError("pass OrganizationFilter or keyword filters, not both")
        request = filters or OrganizationFilter(**options)
        if request.favorite is not None and not isinstance(request.favorite, bool):
            raise OrganizationError("favorite filter must be boolean")
        sort_by = str(request.sort_by or "updated").lower()
        if sort_by not in {"title", "created", "updated", "manual"}:
            raise OrganizationError("sort_by must be title, created, updated or manual")
        wanted_tags = {_key(tag, "tag") for tag in request.tags}
        folder = _key(request.folder_id, "folder id") if request.folder_id else None
        category = _key(request.category, "category") if request.category else None
        query = str(request.query or "").strip().casefold()
        try:
            records = self._repository.list_conversations(self._character_id)
        except Exception as exc:
            raise OrganizationRepositoryError(str(exc)) from exc
        selected = []
        for raw in records:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            record = copy.deepcopy(raw)
            org = _organization(record.get("metadata"))
            tags = {_key(tag, "tag") for tag in org.get("tags", [])}
            if folder and _key(org.get("folder_id") or DEFAULT_FOLDER_ID, "folder") != folder:
                continue
            if wanted_tags and not wanted_tags.issubset(tags):
                continue
            if request.favorite is not None and bool(org.get("favorite", False)) != request.favorite:
                continue
            if category and _key(org.get("category") or "", "category") != category:
                continue
            if query and query not in str(record.get("title") or "").casefold() and query not in str(org.get("description") or "").casefold():
                continue
            record["organization"] = org
            selected.append(record)
        if sort_by == "title":
            key_fn = lambda row: str(row.get("title") or "").casefold()
        elif sort_by == "created":
            key_fn = lambda row: str(row.get("created_at") or "")
        elif sort_by == "manual":
            def key_fn(row):
                value = _organization(row.get("metadata")).get("order", 0)
                try:
                    position = int(value)
                except (TypeError, ValueError, OverflowError):
                    position = 0
                return position, str(row.get("id"))
        else:
            key_fn = lambda row: str(row.get("updated_at") or "")
        selected.sort(key=key_fn, reverse=bool(request.descending) if sort_by != "manual" else False)
        return selected
