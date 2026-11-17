"""Kira application entry point.

Application composition is owned by :mod:`kira.app.bootstrap`. The desktop
window is assembled from feature-oriented UI mixins in :mod:`kira.ui.main_window`.
"""
from __future__ import annotations


def main() -> None:
    """Start Kira through the application composition root."""
    from .app.bootstrap import run_application

    run_application()


def __getattr__(name: str):
    """Lazy compatibility export for callers importing MainWindow."""
    if name == "MainWindow":
        from .ui.main_window import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    main()
