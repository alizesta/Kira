"""Qt image codec and Live transport adapters for Vision."""

from __future__ import annotations

from typing import Callable

from ..live_video_selector import SAMPLE_HEIGHT, SAMPLE_WIDTH
from ..vision_runtime_services import EncodedLiveFrame


class QtVisionFrameCodec:
    """Encode QImage frames without leaking Qt imports into Vision services."""

    @staticmethod
    def _write_jpeg(frame, quality: int) -> bytes:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice

        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.WriteOnly):
            return b""
        if not frame.save(buffer, "JPEG", int(quality)):
            return b""
        return bytes(data)

    def encode_jpeg(self, frame, quality: int) -> bytes:
        return self._write_jpeg(frame, quality)

    @staticmethod
    def encode_perception_sample(frame) -> bytes:
        """Create the low-cost grayscale signature used by local change detection."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        thumbnail = frame.scaled(
            32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation
        ).convertToFormat(QImage.Format_Grayscale8)
        return bytes(
            thumbnail.pixelColor(x, y).red()
            for y in range(thumbnail.height())
            for x in range(thumbnail.width())
        )

    def encode_analysis_frame(self, frame, quality: int) -> tuple[bytes, bytes]:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        jpeg = self._write_jpeg(frame, quality)
        if not jpeg:
            return b"", b""
        thumbnail = frame.scaled(
            32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation
        ).convertToFormat(QImage.Format_Grayscale8)
        visual_sample = bytes(
            thumbnail.pixelColor(x, y).red()
            for y in range(thumbnail.height())
            for x in range(thumbnail.width())
        )
        return jpeg, visual_sample

    @staticmethod
    def _quantize_live_image(image):
        from PySide6.QtGui import QImage

        levels = 16
        lookup = bytes(
            (((value * (levels - 1) + 127) // 255) * 255 + (levels - 1) // 2)
            // (levels - 1)
            for value in range(256)
        )
        rgb = image.convertToFormat(QImage.Format_RGB888)
        quantized = bytes(rgb.constBits()).translate(lookup)
        return QImage(
            quantized,
            rgb.width(),
            rgb.height(),
            rgb.bytesPerLine(),
            QImage.Format_RGB888,
        ).copy()

    @staticmethod
    def _gray_sample(image) -> bytes:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        small = image.scaled(
            SAMPLE_WIDTH,
            SAMPLE_HEIGHT,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        ).convertToFormat(QImage.Format_Grayscale8)
        stride = small.bytesPerLine()
        raw = bytes(small.constBits())
        return b"".join(
            raw[row * stride:row * stride + SAMPLE_WIDTH]
            for row in range(SAMPLE_HEIGHT)
        )

    def prepare_live_frame(self, frame, *, width: int, height: int):
        from PySide6.QtCore import Qt

        scaled = frame.scaled(
            int(width), int(height), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        image = self._quantize_live_image(scaled)
        return image, self._gray_sample(image)

    def encode_live_frame(self, image, max_bytes: int) -> EncodedLiveFrame:
        from PySide6.QtCore import Qt

        encoded_image = image
        quality = 35
        jpeg = self._write_jpeg(encoded_image, quality)
        if len(jpeg) > max_bytes:
            for quality in (30, 25, 20):
                jpeg = self._write_jpeg(encoded_image, quality)
                if jpeg and len(jpeg) <= max_bytes:
                    break
        if not jpeg or len(jpeg) > max_bytes:
            for width, height, quality in ((384, 216, 22), (320, 180, 20)):
                encoded_image = image.scaled(
                    width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                jpeg = self._write_jpeg(encoded_image, quality)
                if jpeg and len(jpeg) <= max_bytes:
                    break
        return EncodedLiveFrame(
            jpeg=bytes(jpeg or b""),
            quality=int(quality),
            width=int(encoded_image.width()),
            height=int(encoded_image.height()),
        )


class GeminiLiveTransportAdapter:
    """Narrow callable adapter: the Live service never receives a UI controller."""

    def __init__(
        self,
        *,
        readiness: Callable[[], bool],
        clear_frames: Callable[[], None],
        send_frame: Callable[[bytes], bool],
    ) -> None:
        self._readiness = readiness
        self._clear_frames = clear_frames
        self._send_frame = send_frame

    def is_gemini_live_ready(self) -> bool:
        return bool(self._readiness())

    def clear_gemini_video_frames(self) -> None:
        self._clear_frames()

    def send_gemini_video_frame(self, jpeg: bytes) -> bool:
        return bool(self._send_frame(bytes(jpeg)))
