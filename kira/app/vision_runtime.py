"""Composition-owned Vision runtime graph; no MainWindow dependency."""
from __future__ import annotations

from typing import Any, Callable

from .perception_application import PerceptionApplicationService
from ..vision_runtime_services import (
    LiveSessionManager,
    VisionAnalysisCoordinator,
    VisionCaptureService,
)


class VisionRuntimeServices:
    """Own the single instance of each Vision runtime service for one window."""

    def __init__(
        self,
        *,
        game_mode_adapter: Any,
        game_mode_application_service: Any,
        vision_application_service: Any,
        desktop_context_application_service: Any,
        settings: Any,
        frame_codec: Any,
        live_transport: Any,
        max_frame_bytes_provider: Callable[[], int],
        trace: Callable[..., Any] | None = None,
    ) -> None:
        required = (
            game_mode_adapter, game_mode_application_service,
            vision_application_service, desktop_context_application_service,
            settings, frame_codec, live_transport, max_frame_bytes_provider,
        )
        if any(value is None for value in required):
            raise TypeError("Vision runtime composition requires all dependencies")
        self.frame_codec = frame_codec
        self.capture_service = VisionCaptureService(
            game_mode_adapter, vision_application_service
        )
        self.analysis_coordinator = VisionAnalysisCoordinator(
            vision_application_service,
            frame_codec.encode_analysis_frame,
            capture_service=self.capture_service,
            trace=trace,
        )
        self.live_transport = live_transport
        self.live_session_manager = LiveSessionManager(
            settings,
            self.capture_service,
            vision_application_service,
            game_mode_application_service,
            live_transport,
            frame_codec,
            max_frame_bytes_provider=max_frame_bytes_provider,
            trace=trace,
        )
        self.perception_application_service = PerceptionApplicationService(
            desktop_context_application_service,
            self.capture_service,
            trace=trace,
        )
        self._disposed = False

    def dispose(self) -> bool:
        """Stop accepting Live work and release transport-owned resources."""
        if self._disposed:
            return True
        self.live_session_manager.dispose()
        self._disposed = True
        return True


class VisionRuntimeProvider:
    """Thread-safe-by-construction lazy owner for one window's Vision graph."""

    def __init__(self, factory: Callable[[], VisionRuntimeServices]) -> None:
        if not callable(factory):
            raise TypeError("Vision runtime factory must be callable")
        self._factory = factory
        self._instance: VisionRuntimeServices | None = None
        self._disposed = False

    def get(self) -> VisionRuntimeServices:
        if self._disposed:
            raise RuntimeError("Vision runtime provider is disposed")
        if self._instance is None:
            instance = self._factory()
            if not isinstance(instance, VisionRuntimeServices):
                raise TypeError("Vision runtime factory returned an invalid service graph")
            self._instance = instance
        return self._instance

    def peek(self) -> VisionRuntimeServices | None:
        return self._instance

    def dispose(self) -> bool:
        if self._disposed:
            return True
        if self._instance is not None and not self._instance.dispose():
            return False
        self._disposed = True
        return True
