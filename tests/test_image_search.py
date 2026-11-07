import base64
import os
import tempfile
import time
import unittest
from unittest import mock

from kira import attachments as att
from kira import websearch as ws

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
IMG = [{"mime": "image/png", "b64": base64.b64encode(PNG).decode(), "name": "a.png"}]


class Resp:
    def __init__(self, js, status=200):
        self._js, self.status_code = js, status

    def json(self):
        return self._js


GROUNDED = {"candidates": [{"content": {"parts": [{"text": "A red Siemens SINUMERIK operator panel."}]},
                            "groundingMetadata": {"webSearchQueries": ["siemens sinumerik 840d panel"],
                                                  "groundingChunks": [{"web": {"uri": "https://example.com/p", "title": "Panel"}}],
                                                  "groundingSupports": [{"segment": {"text": "Operator panel."}, "groundingChunkIndices": [0]}]}}]}


class CommandTests(unittest.TestCase):
    def test_force_command(self):
        self.assertEqual(ws.image_command("/img این چیه؟"), ("این چیه؟", True))
        self.assertEqual(ws.image_command("/عکس"), ("", True))
        self.assertEqual(ws.image_command("سلام"), ("سلام", False))
        self.assertEqual(ws.image_command("/imgx"), ("/imgx", False))

    def test_clean_query(self):
        self.assertEqual(ws.clean_query('Query: "siemens 840d"\nextra'), "siemens 840d")
        self.assertEqual(ws.clean_query(""), "")
        self.assertEqual(ws.clean_query("x" * 300), "")

    def test_plain_words_do_not_trigger_web_search(self):
        for text in ("خوبی؟", "دوباره بگو"):
            self.assertEqual(ws.plan(text), (None, False), text)
        self.assertIsNotNone(ws.plan("در وب بگرد قیمت دلار")[0])


class GeminiImageTests(unittest.TestCase):
    def test_picture_and_google_search_sent_together(self):
        with mock.patch("requests.post", return_value=Resp(GROUNDED)) as post:
            found = ws.gemini_image_search(IMG, "این چیه", "KEY", "gemini-flash-latest")
        body = post.call_args.kwargs["json"]
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0]["inline_data"]["mime_type"], "image/png")
        self.assertEqual(body["tools"], [{"google_search": {}}])
        self.assertEqual(found["query"], "siemens sinumerik 840d panel")
        self.assertEqual(found["results"][0]["url"], "https://example.com/p")
        self.assertIn("SINUMERIK", found["image_note"])

    def test_errors_are_persian_search_errors(self):
        with mock.patch("requests.post", return_value=Resp({}, 429)):
            with self.assertRaises(ws.SearchError):
                ws.gemini_image_search(IMG, "", "KEY")
        with self.assertRaises(ws.SearchError):
            ws.gemini_image_search(IMG, "", "")


class ImageResearchTests(unittest.TestCase):
    def test_gemini_first_and_block_is_marked_as_picture_search(self):
        with mock.patch("requests.post", return_value=Resp(GROUNDED)):
            found = ws.image_research(IMG, "", "", "basic", gemini=("KEY", "m"))
        self.assertTrue(found["image"])
        block = ws.format_block(found)
        self.assertIn("برای تصویر ضمیمه", block)
        self.assertIn("توصیف اولیه‌ی تصویر", block)
        self.assertIn("قوانین پاسخ برای جست‌وجوی تصویری", block)
        self.assertNotIn("بررسی خودکار", block)

    def test_without_gemini_a_vision_model_writes_the_query_for_the_text_engines(self):
        fake = {"query": "q", "results": [{"title": "T", "url": "https://a.b", "snippet": "s", "text": ""}], "date": "2026-11-06",
                "engine": "tavily", "mode": "fact"}
        with mock.patch.object(ws, "research", return_value=dict(fake)) as research:
            found = ws.image_research(IMG, "", "TV", "basic", gemini=None, describe=lambda: "Query: siemens 840d panel")
        self.assertEqual(research.call_args.args[0], "siemens 840d panel")
        self.assertTrue(found["image"])

    def test_gemini_failure_falls_back_and_says_so(self):
        fake = {"query": "q", "results": [{"title": "T", "url": "https://a.b", "snippet": "s", "text": ""}], "date": "2026-11-06",
                "engine": "ddg", "mode": "fact"}
        with mock.patch("requests.post", return_value=Resp({}, 500)), mock.patch.object(ws, "research", return_value=dict(fake)):
            found = ws.image_research(IMG, "", "", "basic", gemini=("KEY", "m"), describe=lambda: "something")
        self.assertIn("جست‌وجو با خودِ تصویر ممکن نشد", found["note"])

    def test_nothing_usable_raises(self):
        with self.assertRaises(ws.SearchError):
            ws.image_research(IMG, "", "", "basic", gemini=None, describe=lambda: "")
        with self.assertRaises(ws.SearchError):
            ws.image_research(IMG, "", "", "basic", gemini=None, describe=None)


class ComposeTests(unittest.TestCase):
    def test_lead_text_for_searched_picture(self):
        a = [{"kind": "image", "name": "a.png", "mime": "image/png", "b64": "AAAA"}]
        self.assertIn("جست‌وجوی وب", att.compose("", a, search=True)["model"])
        self.assertNotIn("جست‌وجوی وب", att.compose("", a)["model"])
        self.assertTrue(att.compose("این چیه", a, search=True)["model"].startswith("این چیه"))


class BubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, cond, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def test_file_goes_through_the_tray_chat(self):
        from kira.companion import CompanionBubble
        b = CompanionBubble()
        got = []
        b.submitted.connect(lambda t, f: got.append((t, f)))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("hello file")
            b.add_paths([path])
            self.assertTrue(self.wait(lambda: b.pending_attachments()))
            b.edit.setText("بخوان")
            b._submit()
        self.assertEqual(len(got), 1)
        text, files = got[0]
        self.assertEqual(text, "بخوان")
        self.assertEqual(files[0]["kind"], "text")
        self.assertEqual(b.pending_attachments(), [])               # chips are cleared after sending
        b.close()

    def test_pasted_image_and_image_only_message(self):
        from PySide6.QtGui import QImage
        from kira.companion import CompanionBubble
        b = CompanionBubble()
        got = []
        b.submitted.connect(lambda t, f: got.append((t, f)))
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(0xFF3366)
        b.add_pasted_image(image)
        b._submit()                                                  # no text, only a picture: still sent
        self.assertEqual(got[0][0], "")
        self.assertEqual(got[0][1][0]["kind"], "image")
        b.close()

    def test_empty_input_sends_nothing_and_switch_does_not_echo(self):
        from kira.companion import CompanionBubble
        b = CompanionBubble()
        sent, toggled = [], []
        b.submitted.connect(lambda t, f: sent.append(t))
        b.imageSearchToggled.connect(toggled.append)
        b._submit()
        self.assertEqual(sent, [])
        b.set_image_search(True)                                     # follows the main window: no signal back
        self.assertEqual(toggled, [])
        b.img_btn.setChecked(False)                                  # the person clicks it: signal goes out
        self.assertEqual(toggled, [False])
        b.close()


if __name__ == "__main__":
    unittest.main()
