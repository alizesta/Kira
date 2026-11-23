"""Gemini Live bidirectional audio worker with a native local-device bridge.

The worker owns one Live API websocket session and the sounddevice input/output
streams. It never routes microphone audio through the local STT or Piper path.
"""
from __future__ import annotations

import asyncio
import queue
import threading

from PySide6.QtCore import QThread, Signal

from .audio_devices import resolve_input_device


INPUT_RATE = 16_000
OUTPUT_RATE = 24_000
CHANNELS = 1
CHUNK_FRAMES = 1_600
MAX_INPUT_CHUNKS = 12
MAX_OUTPUT_CHUNKS = 32
MAX_VIDEO_CHUNKS = 1
MAX_VIDEO_FRAME_BYTES = 128 * 1024
VIDEO_FRAME_INTERVAL_SECONDS = 1.0


class LiveVideoFrameGate:
    """Validate JPEG frames and enforce a one-frame-per-second ceiling."""

    def __init__(self, *, interval: float = VIDEO_FRAME_INTERVAL_SECONDS,
                 max_bytes: int = MAX_VIDEO_FRAME_BYTES, clock=None):
        import time
        self.interval = max(0.0, float(interval))
        self.max_bytes = max(1, int(max_bytes))
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._last_at = None

    def accept(self, jpeg: bytes) -> bool:
        payload = bytes(jpeg or b"")
        if (len(payload) < 4 or len(payload) > self.max_bytes
                or not payload.startswith(b"\xff\xd8")
                or not payload.endswith(b"\xff\xd9")):
            return False
        now = self._clock()
        with self._lock:
            if self._last_at is not None and now - self._last_at < self.interval:
                return False
            self._last_at = now
        return True

    def reset(self) -> None:
        with self._lock:
            self._last_at = None


def _is_google_provider(provider_id: str, provider: dict) -> bool:
    pid = str(provider_id or "").strip().lower()
    return (
        pid == "google"
        or pid.startswith("google_")
        or str(provider.get("service") or "").strip().lower() == "google"
        or "generativelanguage.googleapis.com" in str(provider.get("base_url") or "").lower()
    )


def resolve_google_api_key(settings: dict, provider_id: str = "") -> str:
    """Read the key from the existing Connections provider; never duplicate secrets."""
    providers = settings.get("providers") or {}
    selected = str(provider_id or settings.get("gemini_live_provider") or "").strip()
    if selected:
        provider = providers.get(selected)
        if isinstance(provider, dict):
            key = str(provider.get("api_key") or "").strip()
            if key:
                return key
    for pid, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        key = str(provider.get("api_key") or "").strip()
        if key and _is_google_provider(pid, provider):
            return key
    return ""


def _device_index(sd, wanted: str, *, input_device: bool):
    """Resolve the selected PortAudio endpoint; input uses host-API-aware identities."""
    wanted = str(wanted or "").strip()
    if not wanted:
        return None
    if input_device:
        return resolve_input_device(sd, wanted)
    devices = sd.query_devices()
    for index, device in enumerate(devices):
        if device.get("max_output_channels", 0) > 0 and device.get("name") == wanted:
            return index
    return None  # Device was disconnected; use the current system default.


class GeminiLiveWorker(QThread):
    """Low-latency PCM audio streaming to/from Gemini Live on a dedicated thread."""

    state_changed = Signal(str)
    connected = Signal()
    transcript = Signal(str, str)  # role, text
    failed = Signal(str)

    def __init__(self, *, api_key: str, model: str, settings: dict, system_instruction: str = "", parent=None):
        super().__init__(parent)
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "gemini-3.8-live").strip()
        self.settings = settings
        self.system_instruction = str(system_instruction or "").strip()
        self._stop = threading.Event()
        self._loop = None
        self._main_task = None
        self._input_chunks = None  # asyncio.Queue, created on the session event loop
        self._video_chunks = None  # one-slot asyncio.Queue, created on the session event loop
        self._video_ready = threading.Event()
        self._video_gate = LiveVideoFrameGate()
        self._send_lock = None  # asyncio.Lock shared by audio/video senders
        self._output_chunks: queue.Queue[bytes] = queue.Queue(MAX_OUTPUT_CHUNKS)
        try:
            self._mic_gain = max(0.5, min(3.0, float(settings.get("mic_gain", 100)) / 100.0))
        except (TypeError, ValueError):
            self._mic_gain = 1.0
        try:
            self._output_gain = max(0.0, min(1.0, float(settings.get("voice_volume", 0.9))))
        except (TypeError, ValueError):
            self._output_gain = 0.9
        self._playback_tail = b""
        self._playback_lock = threading.Lock()
        self._input_stream = None
        self._output_stream = None
        self._failure = ""
        self._transcript_buffers = {"user": [], "assistant": []}

    @property
    def video_ready(self) -> bool:
        return self._video_ready.is_set() and not self._stop.is_set()

    def send_video_frame(self, jpeg: bytes) -> bool:
        """Queue a new JPEG without blocking the capture/UI thread."""
        if not self.video_ready or not self._video_gate.accept(jpeg):
            return False
        loop = self._loop
        if loop is None:
            self._video_gate.reset()
            return False
        try:
            loop.call_soon_threadsafe(self._queue_video_frame, bytes(jpeg))
            return True
        except RuntimeError:
            self._video_gate.reset()
            return False

    def _queue_video_frame(self, payload: bytes) -> None:
        frames = self._video_chunks
        if frames is None or self._stop.is_set():
            return
        if frames.full():
            try:
                frames.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            frames.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def _clear_video_queue_on_loop(self) -> None:
        frames = self._video_chunks
        if frames is None:
            return
        while True:
            try:
                frames.get_nowait()
            except asyncio.QueueEmpty:
                break

    def clear_video_frames(self) -> None:
        """Discard queued images as soon as Live/source permission closes."""
        self._video_gate.reset()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._clear_video_queue_on_loop)
            except RuntimeError:
                pass

    def stop(self):
        self._stop.set()
        self._video_ready.clear()
        self.clear_video_frames()
        loop, task = self._loop, self._main_task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def _on_input(self, indata, frames, timing, status):
        if self._stop.is_set() or self._loop is None:
            return
        import numpy as np
        audio = indata
        if self._mic_gain != 1.0:
            audio = np.clip(indata.astype(np.float32) * self._mic_gain, -32768, 32767).astype("<i2")
        payload = audio.tobytes()
        try:
            self._loop.call_soon_threadsafe(self._queue_input_chunk, payload)
        except RuntimeError:
            pass

    def _queue_input_chunk(self, payload):
        chunks = self._input_chunks
        if chunks is None or self._stop.is_set():
            return
        if chunks.full():
            try:
                chunks.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            chunks.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def _on_output(self, outdata, frames, timing, status):
        needed = frames * CHANNELS * 2
        with self._playback_lock:
            if len(self._playback_tail) < needed:
                pieces = [self._playback_tail]
                total = len(self._playback_tail)
                self._playback_tail = b""
                while total < needed:
                    try:
                        chunk = self._output_chunks.get_nowait()
                    except queue.Empty:
                        break
                    pieces.append(chunk)
                    total += len(chunk)
                self._playback_tail = b"".join(pieces)
            chunk, self._playback_tail = self._playback_tail[:needed], self._playback_tail[needed:]
        outdata.fill(0)
        if chunk and self._output_gain > 0:
            import numpy as np
            samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
            if self._output_gain != 1.0:
                samples *= self._output_gain
            outdata[:len(samples), 0] = np.clip(samples, -32768, 32767).astype("<i2")

    def _clear_output(self):
        with self._playback_lock:
            while True:
                try:
                    self._output_chunks.get_nowait()
                except queue.Empty:
                    break
            self._playback_tail = b""

    async def _send_audio(self, session, types):
        while not self._stop.is_set():
            chunk = await self._input_chunks.get()
            async with self._send_lock:
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={INPUT_RATE}")
                )

    async def _send_video(self, session, types):
        while not self._stop.is_set():
            chunk = await self._video_chunks.get()
            if self._stop.is_set():
                return
            async with self._send_lock:
                await session.send_realtime_input(
                    video=types.Blob(data=chunk, mime_type="image/jpeg")
                )

    async def _receive(self, session):
        while not self._stop.is_set():
            async for response in session.receive():
                if self._stop.is_set():
                    return
                go_away = getattr(response, "go_away", None)
                if go_away is not None:
                    raise RuntimeError(f"Gemini Live is closing the session: {go_away}")
                content = getattr(response, "server_content", None)
                if content is None:
                    continue
                if getattr(content, "interrupted", False):
                    self._clear_output()
                model_turn = getattr(content, "model_turn", None)
                for part in getattr(model_turn, "parts", ()) if model_turn else ():
                    inline = getattr(part, "inline_data", None)
                    data = getattr(inline, "data", None) if inline else None
                    if data:
                        try:
                            self._output_chunks.put_nowait(bytes(data))
                        except queue.Full:
                            # Old audio is less useful than the current live response.
                            try:
                                self._output_chunks.get_nowait()
                                self._output_chunks.put_nowait(bytes(data))
                            except queue.Empty:
                                pass
                input_transcription = getattr(content, "input_transcription", None)
                output_transcription = getattr(content, "output_transcription", None)
                input_text = str(getattr(input_transcription, "text", "") or "")
                output_text = str(getattr(output_transcription, "text", "") or "")
                if input_text:
                    self._transcript_buffers["user"].append(input_text)
                if output_text:
                    self._transcript_buffers["assistant"].append(output_text)
                if getattr(content, "turn_complete", False):
                    for role in ("user", "assistant"):
                        value = "".join(self._transcript_buffers[role]).strip()
                        if value:
                            self.transcript.emit(role, value)
                        self._transcript_buffers[role].clear()

    async def _run_session(self):
        if self._stop.is_set():
            return
        from google import genai
        from google.genai import types
        import sounddevice as sd

        if not self.api_key:
            raise RuntimeError("کلید Google AI در بخش اتصالات انتخاب نشده است.")
        client = genai.Client(api_key=self.api_key)
        self._input_chunks = asyncio.Queue(MAX_INPUT_CHUNKS)
        self._video_chunks = asyncio.Queue(MAX_VIDEO_CHUNKS)
        self._send_lock = asyncio.Lock()
        config_values = {
            "response_modalities": ["AUDIO"],
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=str(self.settings.get("gemini_voice") or "Zephyr"))
                )
            ),
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
        }
        if self.system_instruction:
            config_values["system_instruction"] = self.system_instruction
        proactivity_type = getattr(types, "ProactivityConfig", None)
        if callable(proactivity_type) and bool(self.settings.get("gemini_live_proactive_audio", True)):
            config_values["proactivity"] = proactivity_type(proactive_audio=True)
        config = types.LiveConnectConfig(**config_values)
        mic_device = _device_index(sd, self.settings.get("mic_device", ""), input_device=True)
        output_device = _device_index(sd, self.settings.get("output_device", ""), input_device=False)
        async with client.aio.live.connect(model=self.model, config=config) as session:
            if self._stop.is_set():
                return
            self._input_stream = sd.InputStream(
                device=mic_device, samplerate=INPUT_RATE, channels=CHANNELS,
                dtype="int16", blocksize=CHUNK_FRAMES, callback=self._on_input,
            )
            self._output_stream = sd.OutputStream(
                device=output_device, samplerate=OUTPUT_RATE, channels=CHANNELS,
                dtype="int16", blocksize=CHUNK_FRAMES, callback=self._on_output,
            )
            self._input_stream.start()
            self._output_stream.start()
            self._video_ready.set()
            self.connected.emit()
            self.state_changed.emit("gemini_live")
            async with asyncio.TaskGroup() as group:
                group.create_task(self._send_audio(session, types))
                group.create_task(self._send_video(session, types))
                group.create_task(self._receive(session))

    def _close_audio(self):
        for stream in (self._input_stream, self._output_stream):
            if stream is None:
                continue
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._input_stream = self._output_stream = None

    @staticmethod
    def _format_failure(exc):
        """Unwrap TaskGroup errors so fallback notices retain the actual cause."""
        nested = getattr(exc, "exceptions", None)
        if nested:
            details = "; ".join(GeminiLiveWorker._format_failure(item) for item in nested)
            return f"{type(exc).__name__}: {details}"
        return f"{type(exc).__name__}: {exc}"

    def run(self):
        self.state_changed.emit("gemini_connecting")
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._main_task = self._loop.create_task(self._run_session())
            self._loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._stop.is_set():
                self._failure = self._format_failure(exc)
        finally:
            self._video_ready.clear()
            self._video_gate.reset()
            self._close_audio()
            if self._loop is not None:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    try:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass
                self._loop.close()
            self._loop = self._main_task = None
            self._input_chunks = None
            self._video_chunks = None
            self._send_lock = None
            if self._failure:
                self.failed.emit(self._failure)
            self.state_changed.emit("stopped")
