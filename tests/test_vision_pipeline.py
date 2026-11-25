"""Unit tests for the bounded desktop/game vision pipeline and optional OCR."""
import base64
import sys
import types
import unittest
from unittest import mock

from kira.vision_pipeline import FrameGate, LatestFrameQueue, frame_signature, policy_for
from kira.vision_ocr import extract_local_text


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


class VisionPipelineTests(unittest.TestCase):
    def test_policy_modes_have_expected_sampling_intervals(self):
        self.assertEqual(policy_for("economic").interval_seconds, 5.0)
        self.assertEqual(policy_for("smart").interval_seconds, 1.0)
        self.assertEqual(policy_for("fast").interval_seconds, 0.5)
        self.assertEqual(policy_for("unknown").name, "economic")

    def test_frame_signature_is_stable_and_empty_safe(self):
        self.assertEqual(frame_signature(b""), b"")
        self.assertEqual(frame_signature(b"same"), frame_signature(b"same"))
        self.assertNotEqual(frame_signature(b"same"), frame_signature(b"different"))

    def test_latest_frame_queue_replaces_stale_pending_frame(self):
        queue = LatestFrameQueue()
        self.assertFalse(queue)
        queue.push("old")
        queue.push("new")
        self.assertEqual(queue.pop(), "new")
        self.assertEqual(queue.dropped, 1)
        self.assertIsNone(queue.pop())

    def test_frame_gate_rate_limits_even_when_monotonic_clock_starts_at_zero(self):
        clock = FakeClock(0.0)
        gate = FrameGate(policy_for("economic"), clock=clock)
        self.assertTrue(gate.accept(b"frame-1"))
        clock.value = 1.0
        self.assertFalse(gate.accept(b"frame-2"))
        clock.value = 5.0
        self.assertTrue(gate.accept(b"frame-2"))
        self.assertEqual(gate.analyzed, 2)

    def test_frame_gate_suppresses_unchanged_visuals_and_accepts_real_change(self):
        clock = FakeClock(10.0)
        gate = FrameGate(policy_for("economic"), clock=clock)
        self.assertTrue(gate.accept(b"jpeg-1", visual_sample=bytes([0] * 16)))
        clock.value += 5.0
        self.assertFalse(gate.accept(b"jpeg-2", visual_sample=bytes([1] * 16)))
        clock.value += 5.0
        self.assertTrue(gate.accept(b"jpeg-3", visual_sample=bytes([255] * 16)))
        self.assertEqual(gate.skipped_unchanged, 1)

    def test_latest_frame_force_bypasses_rate_limit(self):
        clock = FakeClock(10.0)
        gate = FrameGate(policy_for("economic"), clock=clock)
        self.assertTrue(gate.accept(b"first"))
        self.assertTrue(gate.accept(b"second", force=True))

    def test_optional_ocr_uses_a_timeout_and_rejects_oversized_images(self):
        class FakeImage:
            def __init__(self, width=100, height=100):
                self.width, self.height = width, height

            def thumbnail(self, size):
                self.thumbnail_size = size

        class FakeImageContext:
            def __init__(self, image):
                self.image = image

            def __enter__(self):
                return self.image

            def __exit__(self, *args):
                return False

        fake_image = FakeImage()
        pil = types.ModuleType("PIL")
        pil.Image = types.SimpleNamespace(open=lambda _stream: FakeImageContext(fake_image))
        pytesseract = types.ModuleType("pytesseract")
        pytesseract.image_to_string = mock.Mock(return_value="  HELLO  \nworld")
        encoded = base64.b64encode(b"fake-image").decode("ascii")
        with mock.patch.dict(sys.modules, {"PIL": pil, "pytesseract": pytesseract}):
            self.assertEqual(extract_local_text({"b64": encoded}), "HELLO world")
        pytesseract.image_to_string.assert_called_once()
        self.assertEqual(pytesseract.image_to_string.call_args.kwargs["timeout"], 4)

        fake_image.width = fake_image.height = 10000
        pytesseract.image_to_string.reset_mock()
        with mock.patch.dict(sys.modules, {"PIL": pil, "pytesseract": pytesseract}):
            self.assertEqual(extract_local_text({"b64": encoded}), "")
        pytesseract.image_to_string.assert_not_called()

    def test_optional_ocr_fails_closed_for_missing_or_invalid_image_data(self):
        self.assertEqual(extract_local_text({}), "")
        self.assertEqual(extract_local_text({"b64": "not-valid-base64"}), "")
        self.assertEqual(extract_local_text(None), "")


if __name__ == "__main__":
    unittest.main()


class DetailEscalationTests(unittest.TestCase):
    def test_policies_default_to_768x432_and_quality_75_to_80(self):
        from kira.vision_pipeline import POLICIES
        for name in ("economic", "smart"):
            self.assertEqual((POLICIES[name].max_width, POLICIES[name].max_height), (768, 432))
        self.assertTrue(all(75 <= p.jpeg_quality <= 80 for p in POLICIES.values()))

    def test_detail_question_and_unreadable_reply_detection(self):
        from kira.vision_pipeline import reply_was_unreadable, wants_detail_capture
        self.assertTrue(wants_detail_capture("متن ریز منو رو بخون"))
        self.assertTrue(wants_detail_capture("read the small text"))
        self.assertFalse(wants_detail_capture("الان کجای نقشه‌ام؟"))
        self.assertTrue(reply_was_unreadable("the text is too small to read"))
        self.assertFalse(reply_was_unreadable("یه دشمن سمت چپه"))

    def test_detail_constants_are_1280x720_q80(self):
        from kira.vision_pipeline import CAPTURE_DETAIL_JPEG_QUALITY, CAPTURE_DETAIL_MAX_HEIGHT, CAPTURE_DETAIL_MAX_WIDTH
        self.assertEqual((CAPTURE_DETAIL_MAX_WIDTH, CAPTURE_DETAIL_MAX_HEIGHT, CAPTURE_DETAIL_JPEG_QUALITY), (1280, 720, 80))
