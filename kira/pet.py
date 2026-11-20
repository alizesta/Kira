"""Desktop-pet behaviour of the floating companion window (inspired by Mate Engine: hang from the cursor, sit on windows / the taskbar,
dance to the music that is playing).

States: free -> dragging (hangs from the cursor) -> falling (gravity, throw momentum) -> perched (sits on a window title bar or the
taskbar and follows that window) and back. Pure geometry lives in kira.perch, music analysis in kira.music_dance; this class only
drives the window with timers (no threads). Settings keys: companion_perch, companion_hang, auto_dance (all default on).
"""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication

from . import perch
from .perch import Rect, Surface

log = logging.getLogger("kira.pet")
TICK_MS = 16
GRAVITY = 3200.0            # px/s^2 at a 620 px high window; scaled with the window height
TRACK_MS = 150
HOLD_X, HOLD_Y = 0.5, 0.10  # where on the window the cursor holds her while hanging (top of the head)


class PetController(QObject):
    def __init__(self, window, animator, settings=None) -> None:
        super().__init__(window)
        self.w = window
        self.animator = animator
        self.settings = settings if settings is not None else {}
        self.state = "free"
        self.surface: Surface | None = None
        self._anchor = (0, 0)                 # left/top of the perched window (to follow it)
        self._press = None
        self._win0 = QPoint()
        self._moved = False
        self._v = [0.0, 0.0]
        self._last = None                     # (QPointF-like x, y) of the last drag tick, for the swing speed
        self._dancing = False
        self._anim: QPropertyAnimation | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._track = QTimer(self)
        self._track.setInterval(TRACK_MS)
        self._track.timeout.connect(self._on_track)

    # ------------------------------------------------------------ settings / helpers
    def on(self, key: str) -> bool:
        return bool(self.settings.get(key, True))

    def _body(self, *names: str) -> None:
        try:
            self.animator.body.emit(json.dumps(list(names)))
        except Exception:                                       # noqa: BLE001 - the PNG avatar has no body
            pass

    def _view(self):
        return getattr(self.w, "view", None)

    def _screen(self, x=None, y=None):
        point = QPoint(int(x if x is not None else self.w.x() + self.w.width() / 2), int(y if y is not None else self.w.y() + self.w.height() / 2))
        return QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()

    def _floor(self, screen) -> Surface:
        avail, full = screen.availableGeometry(), screen.geometry()
        kind = "taskbar" if avail.bottom() < full.bottom() else "floor"
        return Surface(avail.left(), avail.right(), avail.bottom() + 1, kind)

    def _surfaces(self, screen) -> list[Surface]:
        scale = max(0.5, float(screen.devicePixelRatio()))
        rects = [Rect(r.handle, int(r.left / scale), int(r.top / scale), int(r.right / scale), int(r.bottom / scale))
                 for r in perch.windows_rects(exclude=(int(self.w.winId()),))]
        self._rects = {r.handle: r for r in rects}
        return perch.visible_top_edges(rects, screen_top=screen.geometry().top())

    def _tween(self, x: int, y: int, ms: int = 260, then=None) -> None:
        if self._anim is not None:
            self._anim.stop()
        anim = QPropertyAnimation(self.w, b"pos", self)
        anim.setDuration(ms)
        anim.setEndValue(QPoint(int(x), int(y)))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        if then is not None:
            anim.finished.connect(then)
        self._anim = anim
        anim.start()

    # ------------------------------------------------------------ mouse (called by the avatar overlay / PNG avatar)
    def press(self, gp: QPoint) -> None:
        self._press, self._win0, self._moved = gp, self.w.frameGeometry().topLeft(), False

    def move(self, gp: QPoint) -> None:
        if self._press is None:
            return
        d = gp - self._press
        if not self._moved:
            if d.manhattanLength() <= 6:
                return
            self._moved = True
            self._begin_drag()
        if self.state != "dragging":                           # perch and hang both off: plain window dragging
            self.w.move(self._win0 + d)

    def release(self) -> bool:
        """True when the press was a drag (so it is not also a click)."""
        moved = self._moved
        self._press, self._moved = None, False
        if moved and self.state == "dragging":
            self._end_drag()
        return moved

    # ------------------------------------------------------------ drag = hang from the cursor
    def _begin_drag(self) -> None:
        if not (self.on("companion_perch") or self.on("companion_hang")):
            self.state = "free"
            return
        self._stop_motion()
        self.state, self.surface = "dragging", None
        self._dancing = False
        self._last = (float(self.w.x()), float(self.w.y()))
        self._v = [0.0, 0.0]
        self._body("reset")
        self._send_hang(True, 0.0)
        self._tick.start()

    def _send_hang(self, on: bool, vx: float) -> None:
        view = self._view()
        if view is not None and hasattr(view, "hang"):
            view.hang(on and self.on("companion_hang"), vx)

    def _drag_tick(self) -> None:
        cur = QCursor.pos()
        if self.on("companion_hang"):
            tx, ty = cur.x() - HOLD_X * self.w.width(), cur.y() - HOLD_Y * self.w.height()
        else:
            d = cur - self._press if self._press is not None else QPoint()
            tx, ty = self._win0.x() + d.x(), self._win0.y() + d.y()
        x, y = self.w.x() + (tx - self.w.x()) * 0.4, self.w.y() + (ty - self.w.y()) * 0.4
        lx, ly = self._last
        dt = TICK_MS / 1000.0
        self._v = [self._v[0] * 0.5 + 0.5 * (x - lx) / dt, self._v[1] * 0.5 + 0.5 * (y - ly) / dt]
        self._last = (x, y)
        self.w.move(int(round(x)), int(round(y)))
        self._send_hang(True, self._v[0] / max(1, self.w.height()))

    def _end_drag(self) -> None:
        self._tick.stop()
        self._send_hang(False, 0.0)
        if not self.on("companion_perch"):
            self.state = "free"
            return
        self._body("arms_out")
        self.state = "falling"
        screen = self._screen()
        self._fall_surfaces, self._fall_floor, self._fall_screen = self._surfaces(screen), self._floor(screen), screen
        self._v[0] = max(-1800.0, min(1800.0, self._v[0] * 0.6))
        self._v[1] = max(0.0, min(400.0, self._v[1] * 0.3))
        self._tick.start()

    # ------------------------------------------------------------ timers
    def _on_tick(self) -> None:
        if self.state == "dragging":
            self._drag_tick()
        elif self.state == "falling":
            self._fall_tick()
        else:
            self._tick.stop()

    def _fall_tick(self) -> None:
        dt = TICK_MS / 1000.0
        w, h = self.w.width(), self.w.height()
        self._v[1] += GRAVITY * (h / 620.0) * dt
        self._v[0] *= 0.97
        fx0, fy0 = perch.feet_position(self.w.x(), self.w.y(), w, h)
        x, y = self.w.x() + self._v[0] * dt, self.w.y() + self._v[1] * dt
        geo = self._fall_screen.geometry()
        x = max(geo.left() - w // 3, min(geo.right() - 2 * w // 3, x))
        fx, fy = perch.feet_position(x, y, w, h)
        surface = perch.landing_surface(fx, fy0, self._fall_surfaces, self._fall_floor)
        if fy >= surface.y:
            self._tick.stop()
            self._land(surface, fx)
            return
        self.w.move(int(round(x)), int(round(y)))

    def _land(self, surface: Surface, feet_x: float) -> None:
        self.state, self.surface = "perched", surface
        if surface.handle in getattr(self, "_rects", {}):
            r = self._rects[surface.handle]
            self._anchor = (r.left, r.top)
        w, h = self.w.width(), self.w.height()
        self._body("lower_hands", "sit")
        x, y = perch.place_sitting(w, h, feet_x, surface)
        self._tween(x, y, 260)
        self._track.start()

    def _on_track(self) -> None:
        if self.state != "perched" or self.surface is None:
            self._track.stop()
            return
        screen = self._screen()
        w, h = self.w.width(), self.w.height()
        feet_x = self.w.x() + w / 2
        if self.surface.kind == "window":
            edges = self._surfaces(screen)
            rect = self._rects.get(self.surface.handle)
            ok = rect is not None and any(e.handle == self.surface.handle and e.left <= feet_x <= e.right for e in edges)
            if not ok:
                self._start_fall(screen, edges)
                return
            dx, dy = rect.left - self._anchor[0], rect.top - self._anchor[1]
            if dx or dy:
                self._anchor = (rect.left, rect.top)
                self.surface = Surface(rect.left, rect.right, rect.top, "window", rect.handle)
                if self._anim is not None:
                    self._anim.stop()
                self.w.move(self.w.x() + dx, self.w.y() + dy)
        else:
            floor = self._floor(screen)
            if floor.y != self.surface.y:                       # taskbar moved / resized / auto-hide
                self.surface = floor
                self._place_on_surface(animated=True)

    def _start_fall(self, screen, edges) -> None:
        self._track.stop()
        self.state, self.surface = "falling", None
        self._dancing = False
        self._fall_surfaces, self._fall_floor, self._fall_screen = edges, self._floor(screen), screen
        self._v = [0.0, 0.0]
        self._body("arms_out")
        self._tick.start()

    def _place_on_surface(self, animated: bool = True) -> None:
        if self.surface is None:
            return
        w, h = self.w.width(), self.w.height()
        feet_x = self.w.x() + w / 2
        x, y = (perch.place_standing if self._dancing else perch.place_sitting)(w, h, feet_x, self.surface)
        if animated:
            self._tween(x, y, 260)
        else:
            self.w.move(x, y)

    def _stop_motion(self) -> None:
        self._track.stop()
        self._tick.stop()
        if self._anim is not None:
            self._anim.stop()

    # ------------------------------------------------------------ music
    def on_music(self, state: dict) -> None:
        """Called ~12x/s by kira.music_dance.MusicWatcher: dance while a song plays (standing on her perch), sit again afterwards."""
        want = bool(state.get("on")) and self.on("auto_dance") and self.state in ("free", "perched")
        view = self._view()
        if view is not None and hasattr(view, "music"):
            view.music({**state, "on": want})
        if want == self._dancing:
            return
        self._dancing = want
        if self.state == "perched" and self.surface is not None:
            if want:
                self._body("stand_up")
            else:
                self._body("sit")
            self._place_on_surface(animated=True)
