"""Kira as a 3D VRM avatar (assets/vrm/kira.vrm), drawn by a small three.js page inside Qt WebEngine.

Nothing else changes: the existing EmotionFaceAnimator still owns the state (blink, mouth level from the voice,
emotion members from the EmotionDirector, look direction). VrmView only forwards that state to the page; the page
turns it into an idle pose, blinking, lip-sync and facial expressions.

KiraAvatar is a drop-in replacement for AvatarView: it shows the VRM while Kira is the active character and the
VRM is ready, and the old PNG avatar in every other case (Ren / Mika, missing file or libraries, no WebEngine,
WebGL error). Set KIRA_VRM=0 to force the PNG avatar.
"""
import functools
import http.server
import json
import logging
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from . import vrm_vendor
from .face import AvatarView

log = logging.getLogger("kira.vrm")
VRM_DIR = vrm_vendor.ROOT / "assets" / "vrm"
MODEL = VRM_DIR / "kira.vrm"
READY_TIMEOUT_S = 90


def enabled():
    return os.environ.get("KIRA_VRM", "1") != "0" and MODEL.is_file()


# ---------------------------------------------------------------- local file server (127.0.0.1 only, assets/vrm only)
class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".html": "text/html",
                      ".vrm": "application/octet-stream", "": "application/octet-stream"}

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


_server = None
_server_lock = threading.Lock()


def base_url():
    global _server
    with _server_lock:
        if _server is None:
            handler = functools.partial(_Handler, directory=str(VRM_DIR))
            _server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=_server.serve_forever, name="kira-vrm-files", daemon=True).start()
        return f"http://127.0.0.1:{_server.server_address[1]}/"


# ---------------------------------------------------------------- one-time download of the JS libraries
class _Downloader(QThread):
    done = Signal(bool)

    def run(self):
        self.done.emit(vrm_vendor.download(log.info))


_downloader = None


def when_libraries_ready(callback):
    """Call callback() (GUI thread) once assets/vrm/vendor is complete; starts the download if needed."""
    global _downloader
    if vrm_vendor.ready():
        callback()
        return
    if _downloader is None:
        _downloader = _Downloader()
        _downloader.start()
    _downloader.done.connect(lambda ok: callback() if ok else log.warning("VRM libraries unavailable; PNG avatar stays"))


# ---------------------------------------------------------------- the web view
class _Overlay(QWidget):
    """Transparent layer above the web view: the web view would swallow clicks and window dragging."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._press = None
        self._moved = False

    def _pet(self):
        return getattr(self.window(), "pet", None) if self.owner.draggable else None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._win0 = self.window().frameGeometry().topLeft()
            self._moved = False
            if self._pet() is not None:
                self._pet().press(self._press)

    def mouseMoveEvent(self, e):
        if self._press is None or not self.owner.draggable:
            return
        pet = self._pet()
        if pet is not None:
            pet.move(e.globalPosition().toPoint())
            self._moved = self._moved or pet._moved
            return
        d = e.globalPosition().toPoint() - self._press
        if d.manhattanLength() > 6:
            self._moved = True
        if self._moved:
            self.window().move(self._win0 + d)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            pet = self._pet()
            moved = pet.release() if pet is not None else self._moved
            if not moved:
                self.owner.on_click(e.position())
        self._press = None

    def contextMenuEvent(self, e):
        if self.owner.draggable:
            self.window().hide()


class VrmView(QWidget):
    clicked = Signal(str)
    state_changed = Signal(str)        # "ready" | "error"

    def __init__(self, animator, view="full", draggable=False, parent=None):
        super().__init__(parent)
        self.anim = animator
        self.view_kind = view
        self.draggable = draggable
        self.ready = False
        self.failed = False
        self.web = None
        self._polls = 0
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.web = QWebEngineView(self)
            self.web.setAttribute(Qt.WA_TranslucentBackground, True)
            self.web.page().setBackgroundColor(Qt.transparent)
            self.web.setContextMenuPolicy(Qt.NoContextMenu)
            lay.addWidget(self.web)
        except Exception as exc:                        # noqa: BLE001 - PySide6 without WebEngine: PNG avatar stays
            log.warning("Qt WebEngine unavailable: %s", exc)
            self.failed = True
            return
        self.overlay = _Overlay(self)
        self.overlay.raise_()
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._check)
        animator.changed.connect(self._push)
        if hasattr(animator, "gesture"):
            animator.gesture.connect(self._gesture)
        if hasattr(animator, "body"):
            animator.body.connect(self._body)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.web is not None:
            self.overlay.setGeometry(self.rect())
            self.overlay.raise_()

    def start(self):
        if self.web is None or self._poll.isActive() or self.ready:
            return
        self.web.setUrl(QUrl(f"{base_url()}viewer.html?view={self.view_kind}"))
        self._polls = 0
        self._poll.start()

    def _check(self):
        self._polls += 1
        if self._polls * 0.5 > READY_TIMEOUT_S:
            self._finish(False, "timeout")
            return
        self.web.page().runJavaScript("window.kiraStatus", self._status)

    def _status(self, value):
        if value == "ready":
            self._finish(True, "")
        elif isinstance(value, str) and value.startswith("error"):
            self._finish(False, value)

    def _finish(self, ok, why):
        self._poll.stop()
        self.ready, self.failed = ok, not ok
        if ok:
            self.anim.body_enabled = True                  # the chat may now move her body
        if not ok:
            log.warning("VRM avatar failed: %s", why)
        self.state_changed.emit("ready" if ok else "error")

    # ---- state -> page
    def _push(self):
        if not self.ready or not self.isVisible():
            return
        a = self.anim
        fr = getattr(a, "last_frame", None)
        members = [[m[0], m[1], m[2]] for m in fr.members] if (fr is not None and fr.active) else []
        state = {"lid": round(a.lid, 3), "blink": round(a.blink, 3), "mouth": round(a.mouth, 3),
                 "open": round(a.cur["open"], 3), "smile": round(a.cur["smile"], 3), "blush": round(a.cur["blush"], 3),
                 "expr": a.expr, "sleeping": bool(a.sleeping), "look": [round(a._look[0], 3), round(a._look[1], 3)],
                 "members": members}
        self.web.page().runJavaScript(f"window.kiraSet&&window.kiraSet({json.dumps(state)})")

    # ---- clicks
    def region_at(self, pos):
        x, y = pos.x() / max(1, self.width()), pos.y() / max(1, self.height())
        card = self.view_kind == "card"
        if y < (0.14 if card else 0.1):
            return "hair"
        if y < (0.4 if card else 0.24):
            return "face"
        if x < 0.25:
            return "arm_l"
        if x > 0.75:
            return "arm_r"
        if card or y < 0.55:
            return "torso"
        return "legs" if y < 0.9 else "feet"

    def _gesture(self, name):
        if self.ready and self.isVisible():
            self.web.page().runJavaScript(f"window.kiraReact&&window.kiraReact({json.dumps(str(name))})")

    def _body(self, payload):
        """payload: JSON list of kira.body command names (raise_right_hand, turn_back, reset, ...)."""
        if self.ready and self.isVisible():
            self.web.page().runJavaScript(f"window.kiraBody&&window.kiraBody({json.dumps(str(payload))})")

    def hang(self, on, vx):
        """Hold her by the head (on) with the given horizontal swing speed in window-heights / s; off lets go."""
        if self.ready and self.isVisible():
            self.web.page().runJavaScript(f"window.kiraHang&&window.kiraHang({json.dumps({'on': bool(on), 'vx': round(float(vx), 3)})})")

    def music(self, state):
        """state: {on, level, bpm, beats} from kira.music_dance (already gated by the pet controller)."""
        if self.ready and self.isVisible():
            self.web.page().runJavaScript(f"window.kiraMusic&&window.kiraMusic({json.dumps(state)})")

    def on_click(self, pos):
        if not self.ready:
            self.clicked.emit(self.region_at(pos))
            return
        nx, ny = pos.x() / max(1, self.width()), pos.y() / max(1, self.height())
        # the page finds the body part under the click (3D), empty space gives ''
        self.web.page().runJavaScript(f"window.kiraPick&&window.kiraPick({nx:.4f},{ny:.4f})",
                                      lambda region: self.clicked.emit(str(region)) if region else None)


# ---------------------------------------------------------------- drop-in avatar widget
class KiraAvatar(QStackedWidget):
    """AvatarView with a VRM page in front of it whenever Kira is the active character and the VRM is ready."""
    clicked = Signal(str)

    def __init__(self, animator, view="full", draggable=False, parent=None):
        super().__init__(parent)
        self.anim = animator
        self.draggable = draggable
        self._view = view
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.png = AvatarView(animator, view=view, draggable=draggable)
        self.png.clicked.connect(self.clicked)
        self.addWidget(self.png)
        self.vrm = None
        self._wanted = enabled()
        animator.art_changed.connect(self._sync)

    def showEvent(self, e):
        super().showEvent(e)
        if self._wanted and self.vrm is None:
            self._wanted = False                         # start only once per widget
            when_libraries_ready(self._create_vrm)

    def _create_vrm(self):
        try:
            self.vrm = VrmView(self.anim, view=self._view, draggable=self.draggable)
        except Exception as exc:                         # noqa: BLE001
            log.warning("VRM view not created: %s", exc)
            return
        if self.vrm.failed:
            self.vrm = None
            return
        self.vrm.clicked.connect(self.clicked)
        self.vrm.state_changed.connect(lambda _s: self._sync())
        self.addWidget(self.vrm)
        self.vrm.start()

    def _vrm_active(self):
        return self.vrm is not None and self.vrm.ready and self.currentWidget() is self.vrm

    def hang(self, on, vx):
        if self._vrm_active():
            self.vrm.hang(on, vx)

    def music(self, state):
        if self._vrm_active():
            self.vrm.music(state)

    def _sync(self):
        use = bool(self.vrm is not None and self.vrm.ready and getattr(self.anim, "kira_art_active", True))
        self.setCurrentWidget(self.vrm if use else self.png)
