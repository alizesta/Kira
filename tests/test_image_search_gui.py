"""Picture search and tray-chat attachments through the real window (Qt offscreen)."""
import base64
import json
import json as _json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kira import attachments as att
from kira import websearch as ws
from tests import test_gui_routes as base                 # module import: the loader must not collect its test classes here
from tests.test_gui_routes import HAVE_QT, pump, table, sse, StreamResp

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
FOUND = {"query": "siemens 840d panel", "date": "2026-11-06", "engine": "google", "mode": "fact", "image": True, "assessment": {},
         "image_note": "red operator panel", "results": [{"title": "Panel page", "url": "https://example.com/p", "snippet": "Operator panel", "text": ""}]}


def cap_table(mapping):
    """Like table(), but a request that carries pictures sends its body as a progress-reporting stream: decode that too."""
    inner = table(mapping)

    def fake(url, headers=None, json=None, timeout=None, stream=False, data=None, **kw):
        if json is None and data is not None and hasattr(data, "_data"):
            json = _json.loads(data._data.decode("utf-8"))
        return inner(url, headers=headers, json=json, timeout=timeout, stream=stream, **kw)
    fake.calls = inner.calls
    return fake


def dump(call):
    return json.dumps(call["json"], ensure_ascii=False)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ImageSearchGuiTests(unittest.TestCase):
    setUp, tearDown, cloud = base.RouteGuiTests.setUp, base.RouteGuiTests.tearDown, base.RouteGuiTests.cloud

    def image(self):
        return att.image_attachment(PNG, "a.png")

    def run_turn(self, submit, search_result=None, search_error=None):
        w = self.win
        self.cloud("groq")
        f = cap_table({"groq": [StreamResp(sse("باشه"))]})
        search = mock.Mock(return_value=search_result, side_effect=search_error)
        with mock.patch("requests.post", f), mock.patch.object(ws, "image_research", search):
            submit(w)
            self.assertTrue(pump(lambda: not w.busy and (f.calls or search.called)))
            pump(lambda: not w.busy)
        return f, search

    def test_switch_on_picture_is_searched_and_model_gets_sources_and_picture(self):
        self.win.settings["image_search"] = True
        f, search = self.run_turn(lambda w: w.submit("", [self.image()]), FOUND)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(search.call_args.args[0][0]["name"], "a.png")
        body = dump(f.calls[0])
        self.assertIn("image_url", body)                                   # the model still SEES the picture
        self.assertIn("https://example.com/p", body)                       # ... and gets the numbered sources
        self.assertIn("قوانین پاسخ برای جست‌وجوی تصویری", body)

    def test_switch_off_picture_is_not_searched(self):
        self.win.settings["image_search"] = False
        f, search = self.run_turn(lambda w: w.submit("این چیه؟", [self.image()]), FOUND)
        self.assertEqual(search.call_count, 0)
        self.assertIn("image_url", dump(f.calls[0]))

    def test_img_command_forces_search_and_is_removed_from_the_text(self):
        self.win.settings["image_search"] = False
        f, search = self.run_turn(lambda w: w.submit("/img این چیه؟", [self.image()]), FOUND)
        self.assertEqual(search.call_count, 1)
        body = dump(f.calls[0])
        self.assertNotIn("/img", body)
        self.assertIn("این چیه؟", body)

    def test_failed_search_still_answers_from_the_picture_and_says_so(self):
        self.win.settings["image_search"] = True
        f, search = self.run_turn(lambda w: w.submit("", [self.image()]), search_error=ws.SearchError("همه‌ی موتورها خراب"))
        body = dump(f.calls[0])
        self.assertIn("image_url", body)
        self.assertIn("جست‌وجوی وب برای این تصویر انجام نشد", body)
        self.assertIn("جست‌وجوی تصویری انجام نشد", self.win.chat.toPlainText())

    def test_picture_from_the_tray_chat_uses_the_same_pipeline(self):
        self.win.settings["image_search"] = True
        f, search = self.run_turn(lambda w: w.bubble.submitted.emit("", [self.image()]), FOUND)
        self.assertEqual(search.call_count, 1)
        self.assertIn("image_url", dump(f.calls[0]))

    def test_plain_tray_message_still_works_without_attachments(self):
        self.cloud("groq")
        f = cap_table({"groq": [StreamResp(sse("سلام"))]})
        with mock.patch("requests.post", f):
            self.win.bubble.submitted.emit("سلام کیرا", [])
            self.assertTrue(pump(lambda: not self.win.busy and f.calls))
        self.assertNotIn("image_url", dump(f.calls[0]))

    def test_switch_is_shared_between_main_window_and_tray_chat(self):
        w = self.win
        w.img_search_btn.setChecked(True)
        self.assertTrue(w.settings["image_search"])
        self.assertTrue(w.bubble.img_btn.isChecked())
        w.bubble.img_btn.setChecked(False)
        self.assertFalse(w.settings["image_search"])
        self.assertFalse(w.img_search_btn.isChecked())


if __name__ == "__main__":
    unittest.main()
