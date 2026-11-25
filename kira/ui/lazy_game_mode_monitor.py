"""Lazy Qt adapter for foreground game detection and capture."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class LazyGameModeMonitor(QObject):
    """Preserve the monitor contract while deferring native capture imports."""

    game_detected = Signal(dict)

    def __init__(self, parent=None, *, factory: Callable[[], Any] | None = None) -> None:
        super().__init__(parent)
        self._factory = factory if factory is not None else self._create_monitor
        self._monitor: Any | None = None
        self._enabled = False
        self._disposed = False

    def _create_monitor(self):
        from ..game_mode import GameModeMonitor
        return GameModeMonitor(self)

    def _get_monitor(self):
        if self._disposed:
            raise RuntimeError("Game mode monitor has been disposed")
        if self._monitor is None:
            monitor = self._factory()
            if monitor is None:
                raise TypeError("Game mode monitor factory returned None")
            signal = getattr(monitor, "game_detected", None)
            if not callable(getattr(signal, "connect", None)):
                raise TypeError("Game mode monitor must expose a connectable game_detected signal")
            try:
                signal.connect(self.game_detected.emit)
                if self._enabled:
                    monitor.set_enabled(True)
            except Exception as exc:
                try:
                    monitor.set_enabled(False)
                except Exception as cleanup_error:
                    add_note = getattr(exc, "add_note", None)
                    if callable(add_note):
                        add_note(
                            "Game mode monitor cleanup after failed activation also failed: "
                            f"{type(cleanup_error).__name__}: {cleanup_error}"
                        )
                raise
            self._monitor = monitor
        return self._monitor

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_game(self):
        return None if self._monitor is None else self._monitor.last_game

    @property
    def capture_service(self):
        return self._get_monitor().capture_service

    def poll(self) -> None:
        """Retain automatic game detection, importing it on the first timer tick."""
        if not self._disposed:
            self._get_monitor().poll()

    def set_enabled(self, enabled: bool) -> None:
        if self._disposed:
            if enabled:
                raise RuntimeError("Game mode monitor has been disposed")
            return
        self._enabled = bool(enabled)
        if self._monitor is not None:
            self._monitor.set_enabled(self._enabled)
        elif self._enabled:
            self._get_monitor()

    def dispose(self) -> None:
        """Release realized capture resources without realizing a cold monitor."""
        if self._disposed:
            return
        monitor = self._monitor
        if monitor is not None:
            monitor.set_enabled(False)
        self._enabled = False
        self._disposed = True
