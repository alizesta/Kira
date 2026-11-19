"""Own the lifecycle of files and images selected for a chat message.

This controller deliberately knows nothing about MainWindow. Its UI and worker
dependencies are injected, so it can be replaced or tested independently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QBuffer, QIODevice, Slot


class ChatAttachmentController(QObject):
    """Manage pre-send attachment selection, loading, cancellation and tiles."""

    def __init__(
        self,
        *,
        attach_strip,
        error_label,
        error_widget,
        error_close_button,
        send_button,
        is_chat_busy: Callable[[], bool],
        tile_factory,
        worker_factory,
        attachment_api,
        max_files: int,
        parent=None,
    ):
        super().__init__(parent)
        self.attach_strip = attach_strip
        self.error_label = error_label
        self.error_widget = error_widget
        self.error_close_button = error_close_button
        self.send_button = send_button
        self.is_chat_busy = is_chat_busy
        self.tile_factory = tile_factory
        self.worker_factory = worker_factory
        self.attachment_api = attachment_api
        self.max_files = max_files

        self.tiles = []
        self.loading_tiles = []
        self.worker = None
        self.sequence = 0

    @staticmethod
    def _strip_add(strip, tile):
        strip.row.insertWidget(strip.row.count() - 1, tile)
        strip.show()

    @staticmethod
    def _strip_remove(strip, tile):
        strip.row.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        strip.setVisible(strip.row.count() > 1)

    @property
    def attachments(self):
        """Return successfully loaded attachment payloads in display order."""
        return [tile.att for tile in self.tiles if tile.att]

    def show_error(self, messages):
        messages = list(messages or [])
        self.error_label.setText("\n".join(str(message) for message in messages))
        self.error_widget.setVisible(bool(messages))
        self.error_close_button.setVisible(bool(messages))

    def is_loading(self):
        return self.worker is not None and self.worker.isRunning()

    def cancel(self):
        """Cancel active reads and remove their tiles; otherwise dismiss the error."""
        if self.is_loading():
            for index in range(len(self.loading_tiles)):
                self.worker.cancel(index)
            for tile in list(self.tiles):
                self.remove_tile(tile, cancel_worker=False)
        self.show_error([])

    LOADING_TEXT = "در حال بارگذاری ضمیمه‌ها؛ برای لغو روی ضربدر بزن."

    def add_paths(self, paths):
        """Load selected files asynchronously, enforcing the per-message limit."""
        if self.is_loading():
            self.show_error(["صبر کن؛ ضمیمه‌های قبلی هنوز در حال بارگذاری‌اند."])
            return

        paths = list(paths)
        room = self.max_files - len(self.tiles)
        errors = []
        if len(paths) > room:
            errors.append(f"حداکثر {self.max_files} ضمیمه برای هر پیام.")
            paths = paths[:max(0, room)]
        self.show_error(errors)
        if not paths:
            return

        self.loading_tiles.clear()
        for path in paths:
            tile = self.tile_factory(Path(path).name)
            tile.removeRequested.connect(self.remove_tile)
            tile.set_progress(0)
            self.tiles.append(tile)
            self.loading_tiles.append(tile)
            self._strip_add(self.attach_strip, tile)

        self.worker = self.worker_factory(paths)
        self.worker.progress.connect(self.on_progress)
        self.worker.loaded.connect(self.on_loaded)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self._on_worker_finished)
        self.send_button.setEnabled(False)
        self._limit_errors = list(errors)
        self.error_label.setText("\n".join([*errors, self.LOADING_TEXT]))
        self.error_close_button.setVisible(True)
        self.error_widget.show()
        self.worker.start()

    @Slot()
    def _on_worker_finished(self):
        worker = self.sender()
        if worker is not None and self.worker is worker:
            self.worker = None
        self.send_button.setEnabled(not self.is_chat_busy())
        self.on_finished()
        if worker is not None:
            worker.deleteLater()

    def _is_current_worker_signal(self):
        # sender() is None only for direct unit-test/manual invocation. Real Qt
        # worker emissions must belong to the currently tracked read batch.
        sender = self.sender()
        return sender is None or sender is self.worker

    @Slot(int, int)
    def on_progress(self, index, percent):
        if not self._is_current_worker_signal():
            return
        tile = self.loading_tiles[index] if index < len(self.loading_tiles) else None
        if tile is not None and not tile.deleted:
            tile.set_progress(percent)

    @Slot()
    def on_finished(self):
        if self.LOADING_TEXT in self.error_label.text():
            # keep any "limit reached" notice; only drop the transient loading line
            self.show_error(getattr(self, "_limit_errors", []))

    @Slot(int, dict)
    def on_loaded(self, index, attachment):
        if not self._is_current_worker_signal():
            return
        tile = self.loading_tiles[index] if index < len(self.loading_tiles) else None
        if tile is not None and not tile.deleted:
            tile.set_attachment(attachment)
            tile.set_progress(100)

    @Slot(int, str)
    def on_failed(self, index, message):
        if not self._is_current_worker_signal():
            return
        tile = self.loading_tiles[index] if index < len(self.loading_tiles) else None
        if tile is not None and not tile.deleted:
            self.remove_tile(tile)
        self.show_error([message])

    def add_image(self, image):
        """Encode a pasted or captured QImage as a normal PNG attachment."""
        try:
            if len(self.tiles) >= self.max_files:
                raise self.attachment_api.AttachmentError(
                    f"حداکثر {self.max_files} ضمیمه برای هر پیام."
                )
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "PNG")
            self.sequence += 1
            attachment = self.attachment_api.image_attachment(
                bytes(buffer.data()), f"clipboard-{self.sequence}.png"
            )
        except (self.attachment_api.AttachmentError, AttributeError) as exc:
            self.show_error([str(exc)])
            return

        tile = self.tile_factory(attachment["name"])
        tile.removeRequested.connect(self.remove_tile)
        tile.set_attachment(attachment)
        self.tiles.append(tile)
        self._strip_add(self.attach_strip, tile)
        self.show_error([])

    def remove_tile(self, tile, *, cancel_worker=True):
        tile.deleted = True
        if cancel_worker and self.is_loading():
            try:
                self.worker.cancel(self.loading_tiles.index(tile))
            except (ValueError, AttributeError):
                pass
        if tile in self.tiles:
            self.tiles.remove(tile)
        self._strip_remove(self.attach_strip, tile)

    def clear(self):
        for tile in list(self.tiles):
            self.remove_tile(tile)
        self.show_error([])
