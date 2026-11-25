"""Qt worker adapter for the Qt-free PerceptionApplicationService."""

from __future__ import annotations

from PySide6.QtCore import QObject, Slot

from ..app.perception_application import PerceptionApplicationService
from .workers import TaskWorker


class PerceptionWorkerController(QObject):
    """Own only Qt worker creation/signals; perception policy stays in the app service."""

    def __init__(
        self,
        service: PerceptionApplicationService,
        frame_codec,
        settings,
        *,
        is_closing,
        game_mode_enabled,
        trace=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._codec = frame_codec
        self._settings = settings
        self._is_closing = is_closing
        self._game_mode_enabled = game_mode_enabled
        self._trace = trace or (lambda *_args, **_kwargs: None)

    @property
    def worker(self):
        return self._service.worker

    def process_frame(self, frame, source, window_info) -> None:
        ocr_enabled = (
            bool(self._settings.get("desktop_vision_ocr_enabled", True))
            if source == "desktop"
            else bool(self._settings.get("vision_ocr_in_game_mode", False))
        )
        job = self._service.prepare_frame(
            frame,
            source,
            window_info,
            ocr_enabled=ocr_enabled,
            sample_encoder=self._codec.encode_perception_sample,
            jpeg_encoder=self._codec.encode_jpeg,
        )
        if job is None:
            return

        worker = TaskWorker(
            lambda cancelled, request=job: self._service.recognize(
                request, cancelled
            ),
            cancellable=True,
        )
        if not self._service.bind_worker(job, worker):
            worker.deleteLater()
            return

        worker.done.connect(self._on_worker_done)
        worker.finished.connect(self._on_worker_finished)
        try:
            worker.start()
        except RuntimeError as exc:
            released = self._service.worker_start_failed(job, worker)
            self._trace(
                "perception_ocr_start_failed",
                source=source,
                reason=type(exc).__name__,
            )
            if released:
                try:
                    worker.deleteLater()
                except RuntimeError:
                    pass
            return
        self._service.worker_started(job)

    @Slot(object)
    def _on_worker_done(self, result) -> None:
        self._service.accept_worker_result(result)

    @Slot()
    def _on_worker_finished(self) -> None:
        worker = self.sender()
        self._service.finish_worker(
            closing=bool(self._is_closing()),
            game_mode_enabled=bool(self._game_mode_enabled()),
        )
        if worker is not None:
            worker.deleteLater()

    def cancel(self) -> None:
        self._service.cancel()

    def dispose(self) -> bool:
        return self._service.dispose()
