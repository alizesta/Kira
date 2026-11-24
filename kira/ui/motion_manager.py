"""Theme-agnostic animation orchestration for Kira's Qt interface.

The manager owns animation lifetimes and scheduling only. It deliberately does
not choose colours, visual effects, widget layouts, or application behaviour.
All public operations must be called from the manager's Qt thread.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QThread,
)

PropertyName: TypeAlias = str | bytes
Easing: TypeAlias = QEasingCurve | QEasingCurve.Type


@dataclass(frozen=True, slots=True)
class MotionTrack:
    """One QObject property transition used by MotionManager."""

    target: QObject
    property_name: PropertyName
    end_value: Any
    start_value: Any | None = None
    duration_ms: int | None = None
    easing: Easing | None = None


class MotionManager(QObject):
    """Window-scoped owner for reusable Qt property animations.

    Keyed transitions replace an earlier animation with the same key. Unkeyed
    transitions are tracked too and released automatically when they finish.
    The manager does not own a timer or do per-frame Python work; Qt advances
    the properties through its native animation framework.
    """

    DEFAULT_DURATION_MS = 220
    DEFAULT_EASING = QEasingCurve.Type.OutCubic

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        default_duration_ms: int = DEFAULT_DURATION_MS,
        default_easing: Easing = DEFAULT_EASING,
    ) -> None:
        super().__init__(parent)
        self.default_duration_ms = self._validate_duration(default_duration_ms)
        self.default_easing = default_easing
        self._active: dict[int, QAbstractAnimation] = {}
        self._keys: dict[str, int] = {}
        self._closed = False

    @property
    def active_count(self) -> int:
        """Number of currently tracked running or paused animations."""
        return len(self._active)

    @property
    def active_keys(self) -> tuple[str, ...]:
        """Keys of tracked animations, in start order."""
        return tuple(self._keys)

    @property
    def is_shutdown(self) -> bool:
        return self._closed

    def animate(
        self,
        target: QObject,
        property_name: PropertyName,
        end_value: Any,
        *,
        start_value: Any | None = None,
        duration_ms: int | None = None,
        easing: Easing | None = None,
        key: str | None = None,
    ) -> QPropertyAnimation:
        """Animate one writable QObject property and return its Qt animation."""
        self._ensure_available()
        self._validate_key(key)
        track = MotionTrack(
            target=target,
            property_name=property_name,
            start_value=start_value,
            end_value=end_value,
            duration_ms=duration_ms,
            easing=easing,
        )
        animation = self._build_track(track, self, None, None)
        return self._start_animation(animation, key)

    def animate_group(
        self,
        tracks,
        *,
        parallel: bool = True,
        duration_ms: int | None = None,
        easing: Easing | None = None,
        key: str | None = None,
    ) -> QAbstractAnimation:
        """Start property tracks in parallel or in sequence.

        Per-track duration/easing values override group defaults. Tracks
        without overrides inherit this method's arguments, then manager defaults.
        """
        self._ensure_available()
        self._validate_key(key)
        track_list = tuple(tracks)
        if not track_list:
            raise ValueError("animate_group requires at least one MotionTrack")
        if any(not isinstance(track, MotionTrack) for track in track_list):
            raise TypeError("tracks must contain only MotionTrack instances")

        resolved_duration = (
            self.default_duration_ms
            if duration_ms is None
            else self._validate_duration(duration_ms)
        )
        group_type = QParallelAnimationGroup if parallel else QSequentialAnimationGroup
        group = group_type(self)
        try:
            for track in track_list:
                animation = self._build_track(track, group, resolved_duration, easing)
                group.addAnimation(animation)
        except Exception:
            group.deleteLater()
            raise
        return self._start_animation(group, key)

    def stop(self, key: str, *, finish: bool = False) -> bool:
        """Stop a keyed animation; optionally apply its final property values."""
        self._ensure_thread()
        self._validate_key(key, required=True)
        animation_id = self._keys.get(key)
        if animation_id is None:
            return False
        return self._stop_animation(animation_id, finish=finish)

    def stop_all(self, *, finish: bool = False) -> int:
        """Stop all tracked animations and return the number that were active."""
        self._ensure_thread()
        animation_ids = tuple(self._active)
        stopped = 0
        for animation_id in animation_ids:
            if self._stop_animation(animation_id, finish=finish):
                stopped += 1
        return stopped

    def pause(self, key: str) -> bool:
        """Pause a keyed animation without releasing its resources."""
        self._ensure_thread()
        self._validate_key(key, required=True)
        animation = self._animation_for_key(key)
        if animation is None or animation.state() != QAbstractAnimation.State.Running:
            return False
        animation.pause()
        return True

    def resume(self, key: str) -> bool:
        """Resume a keyed animation that is currently paused."""
        self._ensure_thread()
        self._validate_key(key, required=True)
        animation = self._animation_for_key(key)
        if animation is None or animation.state() != QAbstractAnimation.State.Paused:
            return False
        animation.resume()
        return True

    def pause_all(self) -> int:
        """Pause every running animation."""
        self._ensure_thread()
        paused = 0
        for animation in tuple(self._active.values()):
            if animation.state() == QAbstractAnimation.State.Running:
                animation.pause()
                paused += 1
        return paused

    def resume_all(self) -> int:
        """Resume every paused animation."""
        self._ensure_thread()
        resumed = 0
        for animation in tuple(self._active.values()):
            if animation.state() == QAbstractAnimation.State.Paused:
                animation.resume()
                resumed += 1
        return resumed

    def is_running(self, key: str) -> bool:
        """Return whether a keyed animation is advancing (paused is not running)."""
        self._ensure_thread()
        self._validate_key(key, required=True)
        animation = self._animation_for_key(key)
        return animation is not None and animation.state() == QAbstractAnimation.State.Running

    def shutdown(self) -> None:
        """Cancel owned animations and reject new work after accepted app shutdown."""
        self._ensure_thread()
        if self._closed:
            return
        self._closed = True
        self.stop_all()

    def _build_track(
        self,
        track: MotionTrack,
        parent: QObject,
        group_duration: int | None,
        group_easing: Easing | None,
    ) -> QPropertyAnimation:
        target = track.target
        if not isinstance(target, QObject):
            raise TypeError("MotionTrack.target must be a QObject")
        if target.thread() != self.thread():
            raise RuntimeError("animation targets and MotionManager must share a Qt thread")

        property_name = self._normalise_property_name(target, track.property_name)
        duration = (
            track.duration_ms
            if track.duration_ms is not None
            else group_duration if group_duration is not None
            else self.default_duration_ms
        )
        duration = self._validate_duration(duration)
        selected_easing = (
            track.easing
            if track.easing is not None
            else group_easing if group_easing is not None
            else self.default_easing
        )

        animation = QPropertyAnimation(target, property_name, parent)
        try:
            animation.setDuration(duration)
            animation.setEasingCurve(selected_easing)
            if track.start_value is not None:
                animation.setStartValue(track.start_value)
            animation.setEndValue(track.end_value)
        except Exception:
            animation.deleteLater()
            raise
        return animation

    @staticmethod
    def _normalise_property_name(target: QObject, property_name: PropertyName) -> bytes:
        if isinstance(property_name, str):
            encoded = property_name.encode("utf-8")
        elif isinstance(property_name, bytes):
            encoded = property_name
        else:
            raise TypeError("property_name must be str or bytes")
        if not encoded or b"\x00" in encoded:
            raise ValueError("property_name must be a non-empty Qt property name")

        try:
            decoded = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("property_name must be UTF-8") from exc

        index = target.metaObject().indexOfProperty(decoded)
        if index >= 0:
            if not target.metaObject().property(index).isWritable():
                raise ValueError(f"Qt property {decoded!r} is read-only")
            return encoded
        dynamic_names = {bytes(name) for name in target.dynamicPropertyNames()}
        if encoded not in dynamic_names:
            raise ValueError(f"{decoded!r} is not a writable QObject property")
        return encoded

    def _start_animation(
        self,
        animation: QAbstractAnimation,
        key: str | None,
    ) -> QAbstractAnimation:
        self._ensure_available()
        if key is not None:
            previous_id = self._keys.get(key)
            if previous_id is not None:
                self._stop_animation(previous_id, finish=False)

        animation_id = id(animation)
        self._active[animation_id] = animation
        if key is not None:
            self._keys[key] = animation_id
        animation.finished.connect(
            lambda aid=animation_id: self._on_animation_finished(aid)
        )
        try:
            animation.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        except Exception:
            self._release_animation(animation_id)
            raise
        return animation

    def _on_animation_finished(self, animation_id: int) -> None:
        self._release_animation(animation_id)

    def _stop_animation(self, animation_id: int, *, finish: bool) -> bool:
        animation = self._active.get(animation_id)
        if animation is None:
            return False
        if finish:
            duration = animation.duration()
            if duration >= 0:
                animation.setCurrentTime(duration)
        if animation_id not in self._active:
            return True
        animation.stop()
        self._release_animation(animation_id)
        return True

    def _release_animation(self, animation_id: int) -> None:
        animation = self._active.pop(animation_id, None)
        if animation is None:
            return
        for key, active_id in tuple(self._keys.items()):
            if active_id == animation_id:
                self._keys.pop(key, None)
        animation.deleteLater()

    def _animation_for_key(self, key: str) -> QAbstractAnimation | None:
        animation_id = self._keys.get(key)
        return self._active.get(animation_id) if animation_id is not None else None

    def _validate_key(self, key: str | None, *, required: bool = False) -> None:
        if key is None:
            if required:
                raise ValueError("a non-empty animation key is required")
            return
        if not isinstance(key, str) or not key.strip():
            raise ValueError("animation keys must be non-empty strings")

    @staticmethod
    def _validate_duration(duration_ms: int) -> int:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        return duration_ms

    def _ensure_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("MotionManager methods must run on its Qt thread")

    def _ensure_available(self) -> None:
        self._ensure_thread()
        if self._closed:
            raise RuntimeError("MotionManager has been shut down")
