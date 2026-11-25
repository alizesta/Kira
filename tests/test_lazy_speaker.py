from unittest import TestCase
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal

from kira.ui.lazy_speaker import LazySpeaker


class FakeSpeaker(QObject):
    started = Signal()
    finished = Signal()
    cancelled = Signal()
    level = Signal(float)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = {}
        self.calls = []

    def speak(self, text, rate=None, pitch=None, cache=False):
        self.calls.append(("speak", text, rate, pitch, cache))

    def stop(self):
        self.calls.append(("stop",))

    def stream_reset(self):
        self.calls.append(("stream_reset",))

    def stream_text(self, text, final=False):
        self.calls.append(("stream_text", text, final))

    def stream_end(self):
        self.calls.append(("stream_end",))

    def play_file(self, path):
        self.calls.append(("play_file", path))


class LazySpeakerTests(TestCase):
    def test_construction_and_idle_checks_do_not_load_audio_backend(self):
        factory = Mock(side_effect=FakeSpeaker)
        speaker = LazySpeaker(factory, settings={"voice": "test"})
        self.assertFalse(speaker.initialized)
        self.assertEqual(speaker.settings, {"voice": "test"})
        self.assertTrue(speaker.is_idle())
        self.assertFalse(speaker.is_speaking())
        speaker.stop()
        factory.assert_not_called()

    def test_first_speech_constructs_once_and_preserves_signal_contract(self):
        actual = FakeSpeaker()
        factory = Mock(return_value=actual)
        speaker = LazySpeaker(factory, settings={})
        observed = []
        speaker.started.connect(lambda: observed.append("started"))
        speaker.speak("hello", cache=True)
        actual.started.emit()
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(actual.calls, [("speak", "hello", None, None, True)])
        self.assertEqual(observed, ["started"])
        self.assertTrue(speaker.initialized)
