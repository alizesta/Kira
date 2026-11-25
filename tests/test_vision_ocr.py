import subprocess
import unittest
from unittest import mock

from kira.vision_ocr import OcrResult, OcrService, TesseractOcrEngine
from kira.vision_ocr_runtime import TesseractRuntime


class FakeImage:
    width = 500
    height = 300

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def thumbnail(self, size):
        self.thumbnail_size = size


class FakeRuntime:
    def __init__(self, *, ready=True, available=True, missing=()):
        self.status = {
            "engine": "tesseract",
            "status": "Ready" if ready else ("Degraded" if missing else "Available"),
            "installed": True,
            "available": available,
            "ready": ready,
            "initialized": ready,
            "python_bindings_installed": True,
            "python_bindings_ready": True,
            "pillow_installed": True,
            "pillow_ready": True,
            "executable_found": True,
            "binary_ready": True,
            "version": "5.4.0",
            "required_languages": ["fas", "eng"],
            "requested_languages": ["fas", "eng"],
            "installed_languages": ["eng", "fas"],
            "missing_languages": list(missing),
            "persian_ready": "fas" not in missing,
            "english_ready": "eng" not in missing,
            "error_code": "required_language_data_missing" if missing else "",
            "error_stage": "validation" if missing else "",
            "error_message": "Required Tesseract language data is missing: " + ", ".join(missing) if missing else "",
        }
        tess = type("FakeTesseract", (), {})()
        tess.Output = type("Output", (), {"DICT": "dict"})
        tess.image_to_data = mock.Mock(
            return_value={"text": ["Open", "project", ""], "conf": ["90", "80", "-1"]}
        )
        self.pytesseract = tess
        self.image_module = type("ImageModule", (), {"open": mock.Mock(return_value=FakeImage())})
        self.initialize_calls = 0
        self.shutdown_calls = 0

    def discover(self, *, refresh=False):
        return dict(self.status)

    def validate(self, *, refresh=False):
        return dict(self.status)

    def diagnostics(self):
        return dict(self.status)

    def initialize(self):
        self.initialize_calls += 1
        if self.status["available"] and not self.status["missing_languages"]:
            self.status.update(ready=True, initialized=True, status="Ready")
        return dict(self.status)

    def image_config(self, *, page_segmentation_mode=6):
        return f"--psm {page_segmentation_mode}"

    def shutdown(self):
        self.shutdown_calls += 1
        self.status.update(ready=False, initialized=False, status="Available")
        return True


class FakeEngine:
    name = "fake"

    def __init__(self, ready=True):
        self.ready = ready
        self.calls = []
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.allow_initialize = True

    def diagnostics(self):
        return {
            "engine": self.name,
            "status": "Ready" if self.ready else "Degraded",
            "installed": True,
            "available": True,
            "ready": self.ready,
            "requested_languages": ["eng"],
            "persian_ready": False,
            "english_ready": True,
            "error_code": "" if self.ready else "not_ready",
            "error_stage": "" if self.ready else "initialization",
            "error_message": "" if self.ready else "engine has not initialized",
        }

    def validate(self):
        return self.diagnostics()

    def initialize(self):
        self.initialize_calls += 1
        if self.allow_initialize:
            self.ready = True
        return self.diagnostics()

    def shutdown(self):
        self.shutdown_calls += 1
        self.ready = False

    def recognize(self, image_bytes, *, source_frame_id=""):
        self.calls.append((image_bytes, source_frame_id))
        return OcrResult("متن آزمایشی", "eng", .9, source_frame_id=source_frame_id)


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["tesseract"], returncode=returncode, stdout=stdout, stderr=stderr)


class VisionOcrTests(unittest.TestCase):
    def test_result_metadata_and_normalization(self):
        result = OcrResult(
            " line one\n line two ", "fas+eng", 1.4,
            source_frame_id="frame-1", engine="tesseract",
            error_stage="execution", error_message="test failure",
        )
        self.assertEqual(result.text, "line one line two")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.source_frame_id, "frame-1")
        self.assertEqual(result.engine, "tesseract")
        self.assertEqual(result.error_stage, "execution")
        self.assertTrue(result.timestamp_utc)

    def test_tesseract_recognizes_validated_languages(self):
        runtime = FakeRuntime()
        engine = TesseractOcrEngine(runtime=runtime)
        result = engine.recognize(b"jpeg", source_frame_id="f1")
        self.assertEqual(result.text, "Open project")
        self.assertEqual(result.language, "fas+eng")
        self.assertEqual(result.source_frame_id, "f1")
        self.assertEqual(result.engine, "tesseract")
        self.assertAlmostEqual(result.confidence, .85)
        runtime.pytesseract.image_to_data.assert_called_once()

    def test_python_binding_and_pillow_dependencies_are_reported_separately(self):
        runtime = TesseractRuntime(
            paths_provider=lambda: {"executable": "", "executable_candidates": []}
        )
        with (
            mock.patch("kira.vision_ocr_runtime.importlib.util.find_spec",
                       side_effect=lambda name: object() if name == "PIL" else None),
            mock.patch("kira.vision_ocr_runtime.shutil.which", return_value=None),
        ):
            status = runtime.discover(refresh=True)
        self.assertFalse(status["python_bindings_installed"])
        self.assertTrue(status["pillow_installed"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["error_stage"], "discovery")

    def test_missing_binary_is_not_ready(self):
        runtime = TesseractRuntime(
            paths_provider=lambda: {"executable": "", "executable_candidates": []}
        )
        with (
            mock.patch("kira.vision_ocr_runtime.importlib.util.find_spec", return_value=object()),
            mock.patch("kira.vision_ocr_runtime.shutil.which", return_value=None),
        ):
            status = runtime.validate(refresh=True)
        self.assertFalse(status["ready"])
        self.assertFalse(status["binary_ready"])
        self.assertEqual(status["error_code"], "tesseract_executable_not_found")
        self.assertEqual(status["status"], "Degraded")

    def test_required_language_policy_needs_every_configured_language(self):
        runtime = TesseractRuntime(
            required_languages=("fas", "eng"),
            paths_provider=lambda: {"executable": "/fake/tesseract", "tessdata_dir": ""},
        )
        with (
            mock.patch("kira.vision_ocr_runtime.importlib.util.find_spec", return_value=object()),
            mock.patch("kira.vision_ocr_runtime.Path.is_file", return_value=True),
            mock.patch("kira.vision_ocr_runtime.subprocess.run", side_effect=[
                completed(stdout="tesseract 5.4.0"),
                completed(stdout='List of available languages in "/data":\neng\nosd\n'),
            ]),
        ):
            status = runtime.validate(refresh=True)
        self.assertTrue(status["available"])
        self.assertTrue(status["english_ready"])
        self.assertFalse(status["persian_ready"])
        self.assertEqual(status["missing_languages"], ["fas"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["status"], "Degraded")
        self.assertEqual(status["error_stage"], "validation")

    def test_runtime_transitions_from_available_to_ready_and_shutdown(self):
        runtime = FakeRuntime(ready=False)
        engine = TesseractOcrEngine(runtime=runtime)
        self.assertEqual(engine.diagnostics()["status"], "Available")
        self.assertTrue(engine.initialize())
        self.assertTrue(engine.diagnostics()["ready"])
        self.assertTrue(engine.shutdown())
        self.assertEqual(runtime.shutdown_calls, 1)
        self.assertFalse(engine.diagnostics()["ready"])

    def test_validation_failure_contains_engine_language_and_failure_stage(self):
        runtime = FakeRuntime(ready=False, available=True, missing=("fas",))
        result = TesseractOcrEngine(runtime=runtime).recognize(b"jpeg", source_frame_id="frame-7")
        self.assertEqual(result.error_code, "required_language_data_missing")
        self.assertEqual(result.engine, "tesseract")
        self.assertEqual(result.language, "fas+eng")
        self.assertEqual(result.error_stage, "validation")
        self.assertIn("fas", result.error_message)

    def test_discovery_does_not_execute_and_incomplete_engine_cannot_be_selected(self):
        engine = FakeEngine(False)
        service = OcrService({"fake": engine}, selected_engine="fake")
        self.assertFalse(service.diagnostics()["ready"])
        with self.assertRaises(RuntimeError):
            service.select_engine("fake")
        self.assertEqual(engine.calls, [])

    def test_service_selection_and_frame_metadata(self):
        engine = FakeEngine()
        service = OcrService({"fake": engine}, selected_engine="fake")
        service.select_engine("fake")
        result = service.recognize(b"jpeg", source_frame_id="frame-42")
        self.assertEqual(result.text, "متن آزمایشی")
        self.assertEqual(result.source_frame_id, "frame-42")
        self.assertEqual(engine.calls, [(b"jpeg", "frame-42")])

    def test_initialization_failure_can_recover_without_rebuilding_the_service(self):
        engine = FakeEngine(False)
        engine.allow_initialize = False
        service = OcrService({"fake": engine}, selected_engine="fake")
        failed = service.recognize(b"jpeg", source_frame_id="frame-failed")
        self.assertEqual(failed.error_stage, "initialization")
        self.assertEqual(failed.engine, "fake")
        self.assertEqual(engine.calls, [])

        engine.allow_initialize = True
        recovered = service.recognize(b"jpeg", source_frame_id="frame-recovered")
        self.assertEqual(recovered.text, "متن آزمایشی")
        self.assertEqual(recovered.source_frame_id, "frame-recovered")
        self.assertEqual(engine.initialize_calls, 2)

    def test_shutdown_calls_every_registered_engine(self):
        first, second = FakeEngine(), FakeEngine()
        service = OcrService({"first": first, "second": second}, selected_engine="first")
        self.assertTrue(service.shutdown())
        self.assertEqual(first.shutdown_calls, 1)
        self.assertEqual(second.shutdown_calls, 1)
        result = service.recognize(b"jpeg")
        self.assertEqual(result.error_code, "ocr_service_shutdown")

    def test_cancelled_job_does_not_invoke_engine(self):
        engine = FakeEngine()
        service = OcrService({"fake": engine}, selected_engine="fake")
        event = mock.Mock()
        event.is_set.return_value = True
        result = service.recognize(b"jpeg", event)
        self.assertEqual(result.error_code, "cancelled")
        self.assertEqual(engine.calls, [])

    def test_invalid_and_oversized_input(self):
        engine = TesseractOcrEngine(max_image_bytes=4, runtime=FakeRuntime())
        self.assertEqual(engine.recognize(b"").error_code, "empty_image")
        self.assertEqual(engine.recognize(b"12345").error_code, "image_too_large")


if __name__ == "__main__":
    unittest.main()
