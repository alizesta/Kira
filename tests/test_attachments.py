import base64
import os
import tempfile
import unittest
import zipfile

from kira import attachments as att
from unittest import mock

from kira.hybrid_ai import CustomOpenAIProvider, ProgressBody, normalize_messages
from kira.ollama_client import fit_messages

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def path(self, name, data):
        p = os.path.join(self.dir.name, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def test_text_file_utf8_and_cp1256(self):
        a = att.load_attachment(self.path("a.txt", "سلام دنیا".encode("utf-8")))
        self.assertEqual((a["kind"], a["text"]), ("text", "سلام دنیا"))
        b = att.load_attachment(self.path("b.txt", "سلام".encode("cp1256")))
        self.assertEqual(b["text"], "سلام")

    def test_binary_is_rejected(self):
        with self.assertRaises(att.AttachmentError):
            att.load_attachment(self.path("x.bin", b"\x00\x01\x02" * 50))

    def test_docx_text(self):
        p = os.path.join(self.dir.name, "d.docx")
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
               '<w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", xml)
        self.assertEqual(att.load_attachment(p)["text"], "Hello\nWorld")


    def test_zip_reads_text_files_and_lists_non_text_without_extracting(self):
        p = os.path.join(self.dir.name, "project.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("src/main.py", "print('hello')")
            z.writestr("assets/icon.png", b"\\x89PNG")
            z.writestr("../outside.txt", "must not be extracted")
        result = att.load_attachment(p)
        self.assertEqual(result["kind"], "text")
        self.assertIn("src/main.py", result["text"])
        self.assertIn("print('hello')", result["text"])
        self.assertIn("assets/icon.png", result["text"])
        self.assertIn("../outside.txt", result["text"])
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "..", "outside.txt")))

    def test_zip_rejects_corrupt_archive(self):
        with self.assertRaises(att.AttachmentError):
            att.load_attachment(self.path("broken.zip", b"not a zip"))

    def test_file_size_limit_is_higher_than_ten_megabytes(self):
        p = self.path("larger.txt", b"")
        with open(p, "wb") as fh:
            fh.truncate(10 * 1024 * 1024 + 1)
        self.assertEqual(att.load_attachment(p)["size"], 10 * 1024 * 1024 + 1)

    def test_loading_can_be_cancelled(self):
        p = self.path("cancel.txt", b"x" * (1024 * 1024))
        with self.assertRaisesRegex(att.AttachmentError, "لغو"):
            att.load_attachment(p, cancelled=lambda: True)

    def test_image_and_compose(self):
        img = att.load_attachment(self.path("p.png", PNG))
        txt = att.load_attachment(self.path("n.txt", b"line one"))
        packed = att.compose("نظرت؟", [img, txt])
        self.assertIn("line one", packed["model"])
        self.assertEqual(len(packed["images"]), 1)
        self.assertIn("p.png", packed["display"])
        self.assertLess(len(packed["stored"]), 400)                  # history keeps only a short form
        self.assertNotIn(img["b64"], packed["stored"])

    def test_progress_is_reported_up_to_100(self):
        seen = []
        att.load_attachment(self.path("big.txt", b"abc" * 400000), seen.append)          # > 256 KB: several blocks
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(len(seen), 2)

    def test_empty_text_gets_default_prompt(self):
        img = att.load_attachment(self.path("p.png", PNG))
        self.assertTrue(att.compose("", [img])["model"].strip())

    def test_long_file_is_cut(self):
        txt = {"name": "big.txt", "kind": "text", "text": "x" * (att.MAX_TEXT_CHARS + 500)}
        self.assertIn("بریده شد", att.compose("", [txt])["model"])


class ProviderPayloadTests(unittest.TestCase):
    def messages(self):
        return [{"role": "user", "content": "look", "images": [{"mime": "image/png", "b64": "QUJD"}]}]

    def test_normalize_keeps_images_and_merges(self):
        out = normalize_messages(self.messages() + [{"role": "user", "content": "more", "images": [{"mime": "image/png", "b64": "REVG"}]}])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["images"]), 2)

    def test_image_only_message_survives(self):
        out = normalize_messages([{"role": "user", "content": "", "images": [{"mime": "image/png", "b64": "QUJD"}]}])
        self.assertEqual(len(out), 1)

    def test_openai_payload_uses_image_url_parts(self):
        p = CustomOpenAIProvider({"base_url": "http://x/v1", "api_key": "k" * 8, "model": "m"}, name="gemini")
        _, _, payload = p._prepare(self.messages(), "sys", 0.5, False)
        content = payload["messages"][1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "look"})
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD"))

    def test_text_only_payload_unchanged(self):
        p = CustomOpenAIProvider({"base_url": "http://x/v1", "api_key": "k" * 8, "model": "m"}, name="gemini")
        _, _, payload = p._prepare([{"role": "user", "content": "hi"}], "sys", 0.5, False)
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "hi"})

    def test_progress_body_reports_and_keeps_bytes(self):
        seen = []
        body = ProgressBody(b"x" * 1000, seen.append)
        out = b"".join(iter(lambda: body.read(300), b""))
        self.assertEqual(len(out), 1000)
        self.assertEqual(len(body), 1000)
        self.assertEqual(seen[-1], 100)

    def test_images_are_sent_with_progress_body_and_text_is_not(self):
        calls = []

        class Resp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        def fake_post(url, **kw):
            calls.append(kw)
            body = kw.get("data")
            if body is not None:
                while body.read(4096):
                    pass
            return Resp()

        got = []
        p = CustomOpenAIProvider({"base_url": "http://x/v1", "api_key": "k" * 8, "model": "m"}, name="gemini")
        p.upload_progress = got.append
        with mock.patch("kira.hybrid_ai.requests.post", fake_post):
            self.assertEqual(p.chat(self.messages(), "sys", 0.5), "ok")
            self.assertIn("data", calls[0])
            self.assertEqual(calls[0]["headers"]["Content-Type"], "application/json")
            self.assertEqual(got[-1], 100)
            p.chat([{"role": "user", "content": "plain"}], "sys", 0.5)
            self.assertIn("json", calls[1])

    def test_long_text_prompt_is_not_treated_as_a_file_upload(self):
        calls = []

        class Resp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        def fake_post(url, **kw):
            calls.append(kw)
            body = kw.get("data")
            if body is not None:
                while body.read(4096):
                    pass
            return Resp()

        p = CustomOpenAIProvider({"base_url": "http://x/v1", "api_key": "k" * 8, "model": "m"}, name="gemini")
        p.upload_progress = lambda *_: None
        long_prompt = "قانون " * 4000            # over 20 KB once encoded, but still a plain text message
        with mock.patch("kira.hybrid_ai.requests.post", fake_post):
            self.assertEqual(p.chat([{"role": "user", "content": long_prompt}], "sys", 0.5), "ok")
        self.assertIn("json", calls[0])
        self.assertNotIn("data", calls[0])

    def test_ollama_gets_plain_base64_list(self):
        kept = fit_messages(normalize_messages(self.messages()), "sys", 4096)
        self.assertEqual(kept[0]["images"], ["QUJD"])


if __name__ == "__main__":
    unittest.main()
