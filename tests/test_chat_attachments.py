"""Independent contract tests for the non-Qt chat attachment manager."""
import base64
import tempfile
import unittest
from pathlib import Path

from kira.chat.attachments import AttachmentManager, AttachmentError, AttachmentStatus


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


class AttachmentManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = AttachmentManager(self.root / "managed")

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_add_and_get_attachment_is_session_scoped(self):
        item = self.manager.add_attachment(b"hello", filename="note.txt", session_id="kira")
        self.assertEqual(item.status, AttachmentStatus.READY)
        self.assertIsNotNone(self.manager.get_attachment(item.attachment_id, session_id="kira"))
        self.assertIsNone(self.manager.get_attachment(item.attachment_id, session_id="ren"))

    def test_rejects_unknown_extension_and_mismatched_image_content(self):
        with self.assertRaises(AttachmentError):
            self.manager.add_attachment(b"hello", filename="payload.exe", session_id="kira")
        with self.assertRaises(AttachmentError):
            self.manager.add_attachment(b"not an image", filename="photo.png", session_id="kira")

    def test_image_content_is_prepared_without_qt_dependency(self):
        item = self.manager.add_attachment(PNG, filename="pixel.png", session_id="kira")
        prepared = self.manager.prepare_content([item.attachment_id], session_id="kira", text="describe")
        self.assertEqual(len(prepared["images"]), 1)
        self.assertIn("pixel.png", prepared["display"])
        self.assertEqual(prepared["images"][0]["mime"], "image/png")

    def test_text_content_is_prepared_and_message_link_is_preserved(self):
        item = self.manager.add_attachment(
            "سلام".encode("utf-8"), filename="note.txt",
            session_id="mika", message_id="message-1",
        )
        self.assertEqual(item.message_id, "message-1")
        prepared = self.manager.prepare_content([item.attachment_id], session_id="mika")
        self.assertIn("سلام", prepared["model"])
        self.assertEqual(self.manager.list_attachments(session_id="mika", message_id="message-1"), (item,))

    def test_rejects_cross_session_preparation_and_removal(self):
        item = self.manager.add_attachment(b"hello", filename="note.txt", session_id="kira")
        with self.assertRaises(AttachmentError):
            self.manager.prepare_content([item.attachment_id], session_id="ren")
        self.assertFalse(self.manager.remove_attachment(item.attachment_id, session_id="ren"))
        self.assertTrue(Path(item.path).exists())

    def test_size_limit_and_managed_cleanup(self):
        manager = AttachmentManager(self.root / "limited", max_file_bytes=4)
        try:
            with self.assertRaises(AttachmentError):
                manager.add_attachment(b"12345", filename="large.txt", session_id="kira")
        finally:
            manager.close()
        item = self.manager.add_attachment(b"ok", filename="small.txt", session_id="kira")
        self.assertEqual(self.manager.cleanup(session_id="kira"), 1)
        self.assertFalse(Path(item.path).exists())
        self.assertIsNone(self.manager.get_attachment(item.attachment_id, session_id="kira"))


    def test_duplicate_content_is_reused_per_message_and_session(self):
        first = self.manager.add_attachment(
            b"repeat", filename="one.txt", session_id="kira", message_id="m1"
        )
        duplicate = self.manager.add_attachment(
            b"repeat", filename="renamed.txt", session_id="kira", message_id="m1"
        )
        other_session = self.manager.add_attachment(
            b"repeat", filename="one.txt", session_id="ren", message_id="m1"
        )
        other_message = self.manager.add_attachment(
            b"repeat", filename="one.txt", session_id="kira", message_id="m2"
        )
        self.assertEqual(first.attachment_id, duplicate.attachment_id)
        self.assertNotEqual(first.attachment_id, other_session.attachment_id)
        self.assertNotEqual(first.attachment_id, other_message.attachment_id)

    def test_per_message_limit_allows_duplicate_but_rejects_extra_file(self):
        manager = AttachmentManager(self.root / "limited-count", max_files=1)
        try:
            first = manager.add_attachment(b"one", filename="one.txt", session_id="kira", message_id="m1")
            duplicate = manager.add_attachment(b"one", filename="one.txt", session_id="kira", message_id="m1")
            self.assertEqual(first.attachment_id, duplicate.attachment_id)
            with self.assertRaises(AttachmentError):
                manager.add_attachment(b"two", filename="two.txt", session_id="kira", message_id="m1")
            manager.add_attachment(b"two", filename="two.txt", session_id="kira", message_id="m2")
        finally:
            manager.close()

    def test_one_broken_file_does_not_block_other_attachments(self):
        good = self.manager.add_attachment(b"readable", filename="good.txt", session_id="kira", message_id="m1")
        broken = self.manager.add_attachment(b"initial", filename="broken.txt", session_id="kira", message_id="m1")
        Path(broken.path).write_bytes(b"\\x00\\x01\\x02")
        prepared = self.manager.prepare_content(
            [broken.attachment_id, good.attachment_id], session_id="kira"
        )
        self.assertIn("readable", prepared["model"])
        self.assertEqual(len(prepared["errors"]), 1)
        self.assertIn("broken.txt", prepared["errors"][0])

    def test_message_scoped_cleanup_preserves_other_messages(self):
        first = self.manager.add_attachment(b"first", filename="one.txt", session_id="kira", message_id="m1")
        second = self.manager.add_attachment(b"second", filename="two.txt", session_id="kira", message_id="m2")
        self.assertEqual(self.manager.cleanup(session_id="kira", message_id="m1"), 1)
        self.assertFalse(Path(first.path).exists())
        self.assertTrue(Path(second.path).exists())

    def test_metadata_is_immutable(self):
        item = self.manager.add_attachment(
            b"ok", filename="data.txt", session_id="kira",
            metadata={"nested": {"labels": ["safe"]}},
        )
        with self.assertRaises(TypeError):
            item.metadata["new"] = "value"
        with self.assertRaises(TypeError):
            item.metadata["nested"]["new"] = "value"

    def test_remove_refuses_paths_outside_managed_root(self):
        item = self.manager.add_attachment(b"ok", filename="small.txt", session_id="kira")
        record = self.manager._records[item.attachment_id]
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        self.manager._records[item.attachment_id] = type(record)(
            attachment_id=record.attachment_id, message_id=record.message_id,
            session_id=record.session_id, filename=record.filename,
            mime_type=record.mime_type, size=record.size, source=record.source,
            path=str(outside), metadata=record.metadata, status=record.status,
        )
        self.assertFalse(self.manager.remove_attachment(item.attachment_id, session_id="kira"))
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
