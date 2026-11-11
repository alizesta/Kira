"""Optional Qt WebEngine host for the local VRM viewer.

Only the user-selected model path is served, over a loopback-only HTTP server.
The viewer never uploads or copies the VRM file.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..config import DATA_DIR
from .metadata import inspect_vrm


class _LoopbackModelServer:
    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path).expanduser().resolve(strict=True)
        self.web_dir = Path(__file__).resolve().parent / "web"
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="Ai1-VRM-HTTP", daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_port}/"

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def _send_file(self, path: Path, content_type: str):
                try:
                    size = path.stat().st_size
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(size))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    if self.command != "HEAD":
                        with path.open("rb") as stream:
                            while True:
                                chunk = stream.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                route = urlparse(self.path).path
                if route in ("/", "/index.html"):
                    target, mime = owner.web_dir / "index.html", "text/html; charset=utf-8"
                elif route == "/viewer.js":
                    target, mime = owner.web_dir / "viewer.js", "text/javascript; charset=utf-8"
                elif route == "/model.vrm":
                    target, mime = owner.model_path, "model/gltf-binary"
                elif route == "/health":
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(body)
                    return
                else:
                    self.send_error(404)
                    return
                if not target.is_file():
                    self.send_error(404)
                    return
                self._send_file(target, mime)

        return Handler

    def close(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class _Bridge(QObject):
    ready = Signal()
    failed = Signal(str)
    clicked = Signal(str)

    def __init__(self, host: "VrmAvatarWidget"):
        super().__init__(host)
        self.host = host

    @Slot()
    def onReady(self):
        self.ready.emit()

    @Slot(str)
    def onError(self, message):
        self.failed.emit(str(message)[:500])

    @Slot(str)
    def onClicked(self, region):
        region = str(region or "body")
        self.clicked.emit(region if region in {"head", "torso", "arms", "legs", "body"} else "body")

    @Slot(int, int)
    def onDrag(self, dx, dy):
        if not self.host.draggable:
            return
        window = self.host.window()
        if window is not None:
            pos = window.pos()
            window.move(pos.x() + int(dx), pos.y() + int(dy))


class VrmAvatarWidget(QWidget):
    """A transparent VRM renderer that follows an existing FaceAnimator/EmotionFaceAnimator."""

    failed = Signal(str)
    ready = Signal()
    clicked = Signal(str)

    def __init__(self, model_path: str | Path, animator, draggable: bool = False, parent=None):
        super().__init__(parent)
        self.animator = animator
        self.model_path = str(Path(model_path).expanduser().resolve())
        self.draggable = bool(draggable)
        self._page_ready = False
        self._disposed = False
        self._last_error = ""
        self._server = _LoopbackModelServer(self.model_path)

        try:
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtWebEngineCore import QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError as exc:
            self._server.close()
            raise RuntimeError(
                "برای نمایش VRM باید ماژول‌های QtWebEngine و QtWebChannel در نصب PySide6 موجود باشند."
            ) from exc

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("background: transparent; border: 0;")
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        self.bridge = _Bridge(self)
        self.bridge.ready.connect(self._on_ready)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.clicked.connect(self.clicked)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("ai1", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadFinished.connect(self._on_load_finished)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._push_frame)
        self._timer.start()

        suffix = "?draggable=1" if self.draggable else ""
        self.view.setUrl(QUrl(self._server.url + suffix))

    def _on_load_finished(self, ok: bool):
        if not ok:
            self._on_failed("صفحه نمایشگر VRM در Qt WebEngine بارگذاری نشد.")

    def _on_ready(self):
        self._page_ready = True
        self.ready.emit()
        self._push_frame()

    def _on_failed(self, message: str):
        if self._disposed or self._last_error:
            return
        self._last_error = str(message or "خطا در نمایش VRM")
        self.failed.emit(self._last_error)

    def _push_frame(self):
        if self._disposed or not self._page_ready or not self.isVisible():
            return
        a = self.animator
        try:
            frame = {
                "emotion": str(getattr(a, "expr", "neutral") or "neutral"),
                "blink": max(0.0, min(1.0, float(getattr(a, "lid", 0.0)))),
                "mouth": max(0.0, min(1.0, float(getattr(a, "mouth", 0.0)))),
                "open": max(0.0, min(1.0, float(getattr(a, "cur", {}).get("open", 0.0)))),
                "speaking": max(0.0, min(1.0, float(getattr(a, "talking", 0.0)))),
                "sleeping": bool(getattr(a, "sleeping", False)),
                "look": list(getattr(a, "_look", [0.0, 0.0])),
            }
            payload = json.dumps(frame, ensure_ascii=True, separators=(",", ":"))
            self.view.page().runJavaScript(f"window.ai1SetFrame && window.ai1SetFrame({payload});")
        except Exception:
            # Animation is supplemental. A transient frame error must not close the desktop app.
            return

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        self.animator.changed.disconnect(self._push_frame) if hasattr(self.animator, "changed") else None
        if self._server is not None:
            self._server.close()
            self._server = None

    def shutdown(self):
        self.dispose()
        self.hide()
