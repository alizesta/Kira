"""Voice tab: the microphone and speaker cards keep only what a person actually needs.

Kept: speaking on/off, output volume, microphone sensitivity and ONE test button that records a few seconds from the
Windows default microphone and plays them back through the Windows default speaker (at the chosen volume).
Hidden (the widgets stay alive, so the saved values and the controllers keep working): microphone and speaker
pickers, the recognition-engine label, the second microphone slider, barge-in, wake time-out and real-time ASR.

The finalizer in _all_pages_fluid_finalizers.py calls simplify_audio_cards(page) once the page is built.
"""
from __future__ import annotations

from array import array

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer
from PySide6.QtWidgets import QFormLayout, QLabel, QPushButton

RECORD_MS = 3000
HEARD_LEVEL = 0.02          # normalised peak below this means the microphone delivered (almost) silence

HIDDEN_MIC_FIELDS = ("mic_device", "engine_lbl", "mic_gain", "barge_chk", "wake_timeout", "real_time_asr_chk")
HIDDEN_OUTPUT_FIELDS = ("out_device",)


def _hide_row(form, widget):
    """Hide a form row (label and field) without destroying the widget."""
    if widget is None:
        return
    try:
        form.setRowVisible(widget, False)
        return
    except (AttributeError, TypeError, RuntimeError):
        pass
    label = form.labelForField(widget)
    if label is not None:
        label.setVisible(False)
    widget.setVisible(False)


def peak_level(data, kind):
    """Largest absolute sample of a raw PCM block as 0..1. kind: int16 | int32 | float | uint8.
    Unknown kinds count as loud so a test is never wrongly reported as silent."""
    try:
        if kind == "int16":
            samples, size, scale = array("h"), 2, 32768.0
        elif kind == "int32":
            samples, size, scale = array("i"), 4, 2147483648.0
        elif kind == "float":
            samples, size, scale = array("f"), 4, 1.0
        elif kind == "uint8":
            samples, size, scale = array("B"), 1, 128.0
        else:
            return 1.0
        usable = len(data) - len(data) % size
        if usable <= 0:
            return 0.0
        samples.frombytes(bytes(data[:usable]))
        if kind == "uint8":
            peak = max(abs(value - 128) for value in samples)
        else:
            peak = max(max(samples), -min(samples))
        return min(1.0, abs(peak) / scale)
    except Exception:  # noqa: BLE001 - a level meter must never break the page
        return 1.0


def _sample_kind(fmt):
    from PySide6.QtMultimedia import QAudioFormat
    sample_format = fmt.sampleFormat()
    formats = QAudioFormat.SampleFormat
    if sample_format == formats.Int16:
        return "int16"
    if sample_format == formats.Int32:
        return "int32"
    if sample_format == formats.Float:
        return "float"
    if sample_format == formats.UInt8:
        return "uint8"
    return ""


class AudioLoopbackTest(QObject):
    """Record RECORD_MS from the default microphone, then play it on the default speaker."""

    def __init__(self, page, button, status):
        super().__init__(page)
        self._page = page
        self._button = button
        self._status = status
        self._phase = "idle"
        self._fmt = None
        self._source = self._sink = self._rec = self._play = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        button.clicked.connect(lambda checked=False: self.start())

    def _say(self, text):
        self._status.setText(text)

    def start(self):
        if self._phase != "idle":
            return
        try:
            from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices
        except Exception:  # noqa: BLE001
            self._say("Qt Multimedia در این نصب در دسترس نیست.")
            return
        mic = QMediaDevices.defaultAudioInput()
        if mic.isNull():
            self._say("هیچ میکروفونی در ویندوز به‌عنوان پیش‌فرض انتخاب نشده.")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not mic.isFormatSupported(fmt):
            fmt = mic.preferredFormat()
        self._fmt = fmt
        self._rec = QBuffer(self)
        self._rec.open(QIODevice.OpenModeFlag.WriteOnly)
        self._source = QAudioSource(mic, fmt, self)
        self._source.start(self._rec)
        if self._source.error() != QAudio.Error.NoError:
            self._say("میکروفون باز نشد. دسترسی میکروفون در تنظیمات حریم خصوصی ویندوز را بررسی کن.")
            self._reset()
            return
        self._phase = "recording"
        self._button.setEnabled(False)
        self._say("در حال ضبط… ۳ ثانیه چیزی بگو.")
        self._timer.start(RECORD_MS)

    def _advance(self):
        if self._phase == "recording":
            self._finish_recording()
        elif self._phase == "playing":
            self._finish_playing()

    def _finish_recording(self):
        data = b""
        if self._source is not None:
            self._source.stop()
        if self._rec is not None:
            data = bytes(self._rec.data().data())
            self._rec.close()
        self._release()
        if peak_level(data, _sample_kind(self._fmt)) < HEARD_LEVEL:
            self._say("از میکروفون صدایی نرسید. میکروفون پیش‌فرض ویندوز یا حساسیت را بررسی کن.")
            self._reset()
            return
        self._start_playback(data)

    def _start_playback(self, data):
        try:
            from PySide6.QtMultimedia import QAudioSink, QMediaDevices
        except Exception:  # noqa: BLE001
            self._say("Qt Multimedia در این نصب در دسترس نیست.")
            self._reset()
            return
        out = QMediaDevices.defaultAudioOutput()
        if out.isNull():
            self._say("هیچ بلندگویی در ویندوز به‌عنوان پیش‌فرض انتخاب نشده.")
            self._reset()
            return
        if not out.isFormatSupported(self._fmt):
            self._say("بلندگوی پیش‌فرض ویندوز این قالب صدا را نمی‌پذیرد.")
            self._reset()
            return
        self._play = QBuffer(self)
        self._play.setData(QByteArray(data))
        self._play.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = QAudioSink(out, self._fmt, self)
        self._sink.setVolume(max(0.0, min(1.0, self._page.volume.value() / 100.0)))
        self._sink.start(self._play)
        self._phase = "playing"
        frames = len(data) // max(1, self._fmt.bytesPerFrame())
        millis = int(frames * 1000 / max(1, self._fmt.sampleRate())) + 500
        self._say("در حال پخش صدای ضبط‌شده…")
        self._timer.start(millis)

    def _finish_playing(self):
        if self._sink is not None:
            self._sink.stop()
        self._release()
        self._say("تمام شد. اگر صدات را شنیدی، میکروفون و بلندگو درست کار می‌کنند.")
        self._reset()

    def _release(self):
        for name in ("_source", "_sink", "_rec", "_play"):
            obj = getattr(self, name)
            if obj is not None:
                if name in ("_rec", "_play") and obj.isOpen():
                    obj.close()
                obj.deleteLater()
                setattr(self, name, None)

    def _reset(self):
        self._timer.stop()
        self._release()
        self._phase = "idle"
        self._button.setEnabled(True)


def simplify_audio_cards(page):
    """Hide the extra rows of the microphone / speaker cards and add the single test button. Safe to call twice."""
    if getattr(page, "_audio_cards_simplified", False):
        return
    sections = getattr(page, "_voice_sections", None)
    if not sections or len(sections) < 2:
        return
    mic_form, out_form = sections[0].layout(), sections[1].layout()
    if not isinstance(mic_form, QFormLayout) or not isinstance(out_form, QFormLayout):
        return
    for name in HIDDEN_MIC_FIELDS:
        _hide_row(mic_form, getattr(page, name, None))
    for name in HIDDEN_OUTPUT_FIELDS:
        _hide_row(out_form, getattr(page, name, None))

    button = QPushButton("تست میکروفن و بلندگو (ضبط ۳ ثانیه و پخش)")
    button.setToolTip("از میکروفون پیش‌فرض ویندوز ضبط می‌کند و با بلندی صدای بالا از بلندگوی پیش‌فرض پخش می‌کند.")
    status = QLabel("")
    status.setObjectName("hint")
    status.setWordWrap(True)
    mic_form.addRow(button)
    mic_form.addRow(status)
    page.audio_test_btn = button
    page.audio_test_status = status
    page._audio_test = AudioLoopbackTest(page, button, status)
    page._audio_cards_simplified = True
    refresh = getattr(page, "refresh_responsive_layout", None)
    if callable(refresh):
        refresh()
