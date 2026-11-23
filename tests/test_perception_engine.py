import unittest

from kira.app.desktop_context import DesktopContext
from kira.perception import ActiveWindowProbe, ChangeDetector, PerceptionEngine
from kira.vision_ocr import OcrResult


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeOcr:
    def recognize(self, image_bytes):
        return OcrResult("Open project", "eng", 0.91)


def window(hwnd=10, pid=20, exe="code.exe", title="project.py"):
    return {
        "hwnd": hwnd, "pid": pid, "exe": exe, "title": title,
        "path": r"C:\Program Files\Code.exe", "rect": (0, 0, 1280, 720),
    }


class PerceptionEngineTests(unittest.TestCase):
    def test_active_window_probe_fails_closed_on_incomplete_identity(self):
        probe = ActiveWindowProbe()
        self.assertIsNone(probe.inspect(None))
        self.assertIsNone(probe.inspect({"hwnd": 1, "pid": 2, "exe": "app.exe"}))
        self.assertEqual(probe.key(window()), (10, 20))

    def test_change_detector_ignores_small_deltas_and_accepts_real_change(self):
        clock = FakeClock()
        detector = ChangeDetector(threshold=0.02, min_interval=1.0, clock=clock)
        first = bytes([0] * 576)
        self.assertTrue(detector.changed(first))
        clock.value = 1.0
        self.assertFalse(detector.changed(bytes([1] * 576)))
        clock.value = 2.0
        self.assertTrue(detector.changed(bytes([255] * 576)))

    def test_engine_updates_context_only_for_the_observed_window(self):
        context = DesktopContext()
        engine = PerceptionEngine(context, FakeOcr())
        normalized = engine.observe_window(window(), source="desktop")
        self.assertIsNotNone(normalized)
        result = engine.recognize(b"fake-jpeg")
        self.assertTrue(engine.apply_ocr(result, window(), source="desktop"))
        self.assertIn("Open project", context.summary())
        self.assertFalse(engine.apply_ocr(result, window(hwnd=99, pid=100), source="desktop"))

    def test_invalid_window_purges_context_and_resets_change_detector(self):
        context = DesktopContext()
        engine = PerceptionEngine(context, FakeOcr())
        engine.observe_window(window())
        engine.apply_ocr(OcrResult("visible text", "eng", 0.8), window())
        self.assertIn("visible text", context.summary())
        self.assertIsNone(engine.observe_window(None))
        self.assertEqual(context.summary(), "")

    def test_ocr_engine_errors_are_returned_as_empty_results(self):
        class BrokenOcr:
            def recognize(self, image_bytes):
                raise RuntimeError("broken")

        engine = PerceptionEngine(DesktopContext(), BrokenOcr())
        result = engine.recognize(b"image")
        self.assertEqual(result.text, "")
        self.assertEqual(result.error_code, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
