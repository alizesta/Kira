"""Explicit, non-destructive export of existing Windows Kira data to Kira Core."""
from __future__ import annotations

import uuid
from collections import defaultdict

from . import characters, persona_memory, routes as route_model
from .config import DB_PATH
from .memory import read_rows_full


def build_import_payload(settings: dict) -> tuple[dict, dict, dict]:
    """Return (shared_data, provider_credentials, preview_counts). Does not mutate or delete local data."""
    local_settings = settings or {}
    providers = local_settings.get("providers") or {}
    cloud_providers = {
        str(pid): dict(cfg)
        for pid, cfg in providers.items()
        if route_model.provider_kind(pid, cfg) == "cloud"
    }
    shared_settings = {
        key: value for key, value in local_settings.items()
        if key not in {"model", "ollama_url", "core_url", "core_device_id", "core_migration_import_id", "core_migration_imported"}
    }
    shared_settings["providers"] = {
        pid: {key: value for key, value in cfg.items() if key not in {"api_key", "token", "secret"}}
        for pid, cfg in cloud_providers.items()
    }
    shared_settings["routes"] = [
        dict(route) for route in route_model.get_routes(local_settings)
        if route_model.provider_kind(route.get("provider", ""), providers.get(route.get("provider", ""))) == "cloud"
    ]
    shared_settings["provider_order"] = [
        pid for pid in local_settings.get("provider_order", []) if pid in cloud_providers
    ]
    if shared_settings.get("manual_route_id") and not any(
        route.get("id") == shared_settings["manual_route_id"] for route in shared_settings["routes"]
    ):
        shared_settings["manual_route_id"] = ""

    profiles = characters.all_profiles(local_settings)
    shared_characters = []
    for character_id, profile in profiles.items():
        item = dict(profile)
        item["id"] = str(character_id)
        item.setdefault("name", str(character_id).title())
        shared_characters.append(item)

    grouped = defaultdict(list)
    for role, content, created_at, character_id in read_rows_full(DB_PATH):
        if role not in ("user", "assistant") or not str(content).strip():
            continue
        grouped[str(character_id or "kira")].append({
            "role": role,
            "content": content,
            "created_at": created_at,
        })

    conversations = []
    for character_id, messages in grouped.items():
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        conversations.append({
            "id": str(uuid.uuid4()),
            "character_id": character_id,
            "title": (first_user.splitlines()[0][:80] if first_user else character_id.title()),
            "messages": messages,
        })

    memories = []
    memory_count = 0
    for character_id in profiles:
        with persona_memory.character_scope(character_id):
            items = persona_memory.list_items()
        if items:
            memories.append({"character_id": character_id, "items": items})
            memory_count += len(items)

    credentials = {}
    for provider_id, cfg in cloud_providers.items():
        api_key = str(cfg.get("api_key") or "").strip()
        if api_key:
            credentials[provider_id] = {
                "api_key": api_key,
                "account_id": cfg.get("account_id"),
            }

    shared_data = {
        "settings": shared_settings,
        "characters": shared_characters,
        "conversations": conversations,
        "memory": memories,
    }
    counts = {
        "characters": len(shared_characters),
        "conversations": len(conversations),
        "messages": sum(len(item["messages"]) for item in conversations),
        "memory_items": memory_count,
        "provider_credentials": len(credentials),
    }
    return shared_data, credentials, counts
