"""Kira application entry point.

Application composition is owned by :mod:`kira.app.bootstrap`. The former
monolithic window is temporarily retained in :mod:`kira.oldmain` while its
features are migrated behind independent contracts.
"""
from __future__ import annotations


def main() -> None:
    """Start Kira through the application composition root."""
    from .app.bootstrap import run_application

    run_application()


def __getattr__(name: str):
    """Temporary compatibility export for integrations importing MainWindow."""
    if name == "MainWindow":
        from .oldmain import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    main()
