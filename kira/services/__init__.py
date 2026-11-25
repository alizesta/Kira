"""Application services independent of UI widgets.

Public service exports remain backwards compatible while each implementation
is imported only when its corresponding name is requested.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "CharacterProfileService": ".character_service",
    "SqliteChatHistoryService": ".chat_history_service",
    "PersonaMemoryService": ".memory_service",
    "MoodStateService": ".mood_service",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
