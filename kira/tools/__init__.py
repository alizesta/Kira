"""Kira tool system public exports.

Keep the package initializer lightweight: importing a small submodule such as
kira.tools.protocol must not import the ToolAgent, built-in registry, or
Windows capability adapters as an incidental package side effect.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ToolAgent": (".agent", "ToolAgent"),
    "build_registry": (".builtin", "build_registry"),
    "ToolRegistry": (".registry", "ToolRegistry"),
    "Tool": (".registry", "Tool"),
    "ToolResult": (".registry", "ToolResult"),
    "READ": (".registry", "READ"),
    "ACTION": (".registry", "ACTION"),
    "SENSITIVE": (".registry", "SENSITIVE"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import a public tool component only when a caller requests that export."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
