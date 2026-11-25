import sys
import types
import unittest
from unittest import mock
from kira.vision_ocr import OcrResult, OcrService, TesseractOcrEngine

class FakeImage:
    width=500
    height=300
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def thumbnail(self,size): self.thumbnail_size=size

class FakeEngine:
    name="fake"
    def __init__(self,ready=True): self.ready=ready; self.calls=[]
    def diagnostics(self):
        return {"engine":self.name,"ready":self.ready,"persian_ready":True,
                "english_ready":True,"error_code":"" if self.ready else "not_ready"}
    def recognize(self,image_bytes,*,source_frame_id=""):
        self.calls.append((image_bytes,source_frame_id))
        return OcrResult("متن آزمایشی","fas+eng",.9,source_frame_id=source_frame_id)

class VisionOcrTests(unittest.TestCase):
    def test_result_metadata_and_normalization(self):
        result=OcrResult(" line one\n line two ","fas+eng",1.4,source_frame_id="frame-1")
        self.assertEqual(result.text,"line one line two")
        self.assertEqual(result.confidence,1.0)
        self.assertEqual(result.source_frame_id,"frame-1")
        self.assertTrue(result.timestamp_utc)

    def test_tesseract_recognizes_detected_languages(self):
        tess=types.ModuleType("pytesseract")
        tess.get_languages=mock.Mock(return_value=["eng","fas"])
        tess.get_tesseract_version=mock.Mock(return_value="5.4.0")
        tess.Output=types.SimpleNamespace(DICT="dict")
        tess.pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract")
        tess.image_to_data=mock.Mock(return_value={"text":["Open","project",""],"conf":["90","80","-1"]})
        pil=types.ModuleType("PIL"); pil.Image=types.SimpleNamespace(open=mock.Mock(return_value=FakeImage()))
        with mock.patch("shutil.which",return_value="tesseract"),mock.patch.dict(sys.modules,{"PIL":pil,"pytesseract":tess}):
            result=TesseractOcrEngine().recognize(b"jpeg",source_frame_id="f1")
        self.assertEqual(result.text,"Open project")
        self.assertEqual(result.language,"fas+eng")
        self.assertEqual(result.source_frame_id,"f1")
        self.assertAlmostEqual(result.confidence,.85)

    def test_python_binding_and_pillow_dependencies_are_reported_separately(self):
        tess = types.ModuleType("pytesseract")
        pil = types.ModuleType("PIL")
        pil.Image = object()
        with mock.patch.dict(sys.modules, {"pytesseract": None, "PIL": pil}):
            status = TesseractOcrEngine().diagnostics()
        self.assertFalse(status["python_bindings_ready"])
        self.assertTrue(status["pillow_ready"])
        self.assertFalse(status["ready"])

    def test_missing_binary_is_not_ready(self):
        tess=types.ModuleType("pytesseract"); tess.get_languages=mock.Mock(return_value=["eng","fas"])
        tess.get_tesseract_version=mock.Mock(return_value="5.4.0")
        tess.pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract")
        pil=types.ModuleType("PIL"); pil.Image=object()
        with mock.patch("shutil.which",return_value=None),mock.patch.dict(sys.modules,{"PIL":pil,"pytesseract":tess}):
            status=TesseractOcrEngine().diagnostics()
        self.assertFalse(status["ready"]); self.assertFalse(status["binary_ready"])

    def test_language_availability_is_separate(self):
        tess=types.ModuleType("pytesseract"); tess.get_languages=mock.Mock(return_value=["eng"])
        tess.get_tesseract_version=mock.Mock(return_value="5.4.0")
        tess.pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract")
        pil=types.ModuleType("PIL"); pil.Image=object()
        with mock.patch("shutil.which",return_value="tesseract"),mock.patch.dict(sys.modules,{"PIL":pil,"pytesseract":tess}):
            status=TesseractOcrEngine().diagnostics()
        self.assertTrue(status["binary_ready"]); self.assertTrue(status["english_ready"])
        self.assertFalse(status["persian_ready"]); self.assertIn("fas",status["missing_languages"])

    def test_discovery_does_not_execute_and_incomplete_engine_cannot_be_selected(self):
        engine=FakeEngine(False); service=OcrService({"fake":engine},selected_engine="fake")
        self.assertFalse(service.diagnostics()["ready"])
        with self.assertRaises(RuntimeError): service.select_engine("fake")
        self.assertEqual(engine.calls,[])

    def test_service_selection_and_frame_metadata(self):
        engine=FakeEngine(); service=OcrService({"fake":engine},selected_engine="fake")
        service.select_engine("fake")
        result=service.recognize(b"jpeg",source_frame_id="frame-42")
        self.assertEqual(result.text,"متن آزمایشی")
        self.assertEqual(result.source_frame_id,"frame-42")
        self.assertEqual(engine.calls,[(b"jpeg","frame-42")])

    def test_cancelled_job_does_not_invoke_engine(self):
        engine=FakeEngine(); service=OcrService({"fake":engine},selected_engine="fake")
        event=mock.Mock(); event.is_set.return_value=True
        self.assertEqual(service.recognize(b"jpeg",event).error_code,"cancelled")
        self.assertEqual(engine.calls,[])

    def test_invalid_and_oversized_input(self):
        engine=TesseractOcrEngine(max_image_bytes=4)
        self.assertEqual(engine.recognize(b"").error_code,"empty_image")
        self.assertEqual(engine.recognize(b"12345").error_code,"image_too_large")

if __name__=="__main__": unittest.main()
