import sys
import types
import unittest
from unittest import mock

from kira.vision_ocr import OcrResult, TesseractOcrEngine


class FakeImage:
    width = 500
    height = 300

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def thumbnail(self, size):
        self.thumbnail_size = size


class VisionOcrTests(unittest.TestCase):
    def test_result_normalizes_text_and_confidence(self):
        result = OcrResult(" line one\n line two ", "fas+eng", 1.4)
        self.assertEqual(result.text, "line one line two")
        self.assertEqual(result.language, "fas+eng")
        self.assertEqual(result.confidence, 1.0)

    def test_tesseract_returns_language_confidence_and_text(self):
        pytesseract = types.ModuleType("pytesseract")
        pytesseract.get_languages = mock.Mock(return_value=["eng", "fas"])
        pytesseract.Output = types.SimpleNamespace(DICT="dict")
        pytesseract.image_to_data = mock.Mock(return_value={
            "text": ["Open", "project", ""],
            "conf": ["90", "80", "-1"],
        })
        image_module = types.SimpleNamespace(open=mock.Mock(return_value=FakeImage()))
        pil = types.ModuleType("PIL")
        pil.Image = image_module
        with mock.patch.dict(sys.modules, {"PIL": pil, "pytesseract": pytesseract}):
            result = TesseractOcrEngine().recognize(b"jpeg")
        self.assertEqual(result.text, "Open project")
        self.assertEqual(result.language, "fas+eng")
        self.assertAlmostEqual(result.confidence, 0.85)
        pytesseract.image_to_data.assert_called_once()

    def test_missing_tesseract_or_language_data_is_non_fatal(self):
        pytesseract = types.ModuleType("pytesseract")
        pytesseract.get_languages = mock.Mock(return_value=["osd"])
        pil = types.ModuleType("PIL")
        pil.Image = types.SimpleNamespace(open=mock.Mock(return_value=FakeImage()))
        with mock.patch.dict(sys.modules, {"PIL": pil, "pytesseract": pytesseract}):
            result = TesseractOcrEngine().recognize(b"jpeg")
        self.assertEqual(result.text, "")
        self.assertEqual(result.error_code, "tesseract_or_language_data_unavailable")

    def test_invalid_or_oversized_input_is_rejected(self):
        engine = TesseractOcrEngine(max_image_bytes=4)
        self.assertEqual(engine.recognize(b"").error_code, "empty_image")
        self.assertEqual(engine.recognize(b"12345").error_code, "image_too_large")


if __name__ == "__main__":
    unittest.main()
