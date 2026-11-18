"""Shared helpers for tests that touch the split MainWindow modules.

MainWindow is a shell spread across ``kira/ui/main_window*.py``. Tests that
used to patch or read the old single ``kira.main`` module use these helpers
instead, so they follow the real module layout.
"""
from __future__ import annotations

import contextlib
import importlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "kira" / "ui"


def main_window_files() -> list[Path]:
    """All MainWindow shell/mixin/composition source files, sorted."""
    return sorted(UI_DIR.glob("main_window*.py"))


def main_window_source() -> str:
    """Concatenated source of the MainWindow shell, mixins and composition."""
    return "\n".join(p.read_text(encoding="utf-8") for p in main_window_files())


def _ui_modules():
    for path in main_window_files():
        yield importlib.import_module(f"kira.ui.{path.stem}")


@contextlib.contextmanager
def patch_ui(name: str, *args, **kwargs):
    """Patch ``name`` in every MainWindow module that binds it.

    Returns the mock created for the first module (all share one mock), so
    callers can assert on calls exactly as with ``mock.patch``.
    """
    modules = [m for m in _ui_modules() if hasattr(m, name)]
    if not modules:
        raise AttributeError(f"no MainWindow module defines {name!r}")
    replacement = args[0] if args else mock.MagicMock(**kwargs)
    if args and kwargs:
        replacement = mock.MagicMock(*args, **kwargs)
    with contextlib.ExitStack() as stack:
        for module in modules:
            stack.enter_context(mock.patch.object(module, name, replacement))
        yield replacement


def window_method_source(name: str) -> str:
    """Source of method ``name`` from whichever MainWindow mixin defines it."""
    import ast

    for path in main_window_files():
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(source, node) or ""
    raise AttributeError(f"no MainWindow module defines method {name!r}")


def window_method_node(name: str):
    """AST node of method ``name`` from any MainWindow module.

    ``__init__`` resolves to ``initialize_main_window`` in the composition
    module, because the shell constructor only delegates to it.
    """
    import ast

    wanted = "initialize_main_window" if name == "__init__" else name
    for path in main_window_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == wanted:
                return node
    raise AttributeError(f"no MainWindow module defines method {name!r}")


def package_source(*subdirs: str) -> str:
    """Concatenated source of the whole ``kira`` package (or given subpackages)."""
    base = ROOT / "kira"
    roots = [base / d for d in subdirs] if subdirs else [base]
    parts = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)
