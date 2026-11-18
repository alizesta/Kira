"""Security and atomicity tests for the local Chat transfer file adapter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kira.infrastructure.chat_transfer_file_adapter import LocalChatTransferFileAdapter


class ChatTransferFileAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kira-transfer-adapter-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adapter = LocalChatTransferFileAdapter()

    def test_read_bytes_returns_regular_file_within_limit(self):
        source = self.root / "input.json"
        source.write_bytes(b'{"ok":true}')
        self.assertEqual(self.adapter.read_bytes(source, max_bytes=11), b'{"ok":true}')

    def test_read_bytes_rejects_oversized_file_before_returning_content(self):
        source = self.root / "large.json"
        source.write_bytes(b"12345")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.adapter.read_bytes(source, max_bytes=4)

    def test_read_bytes_rejects_directory(self):
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.adapter.read_bytes(self.root, max_bytes=100)

    def test_read_bytes_rejects_symlink(self):
        source = self.root / "real.json"
        source.write_bytes(b"{}")
        link = self.root / "link.json"
        try:
            link.symlink_to(source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.adapter.read_bytes(link, max_bytes=100)

    def test_read_bytes_validates_limit(self):
        source = self.root / "empty.json"
        source.write_bytes(b"")
        for value in (-1, True, 1.5, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.adapter.read_bytes(source, max_bytes=value)
        self.assertEqual(self.adapter.read_bytes(source, max_bytes=0), b"")

    def test_write_bytes_atomically_creates_and_replaces_destination(self):
        first = self.adapter.write_bytes_atomically(self.root, "snapshot.json", b"old")
        self.assertEqual(first.read_bytes(), b"old")
        second = self.adapter.write_bytes_atomically(self.root, "snapshot.json", b"new-complete-content")
        self.assertEqual(second, first)
        self.assertEqual(second.read_bytes(), b"new-complete-content")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".kira-transfer-")], [])

    def test_write_bytes_rejects_unsafe_filenames(self):
        outside_name = f"{self.root.name}-outside.json"
        unsafe_filenames = ("", f"../{outside_name}", "nested/file.json", r"nested\file.json", ".hidden.json", "..")
        for filename in unsafe_filenames:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.adapter.write_bytes_atomically(self.root, filename, b"{}")
        self.assertFalse((self.root.parent / outside_name).exists())

    def test_write_bytes_requires_existing_directory_and_bytes(self):
        with self.assertRaises(FileNotFoundError):
            self.adapter.write_bytes_atomically(self.root / "missing", "export.json", b"{}")
        with self.assertRaises(TypeError):
            self.adapter.write_bytes_atomically(self.root, "export.json", "{}")

    def test_failed_replace_keeps_previous_export_and_removes_temporary_file(self):
        destination = self.root / "snapshot.json"
        destination.write_bytes(b"previous-valid-export")
        with patch("kira.infrastructure.chat_transfer_file_adapter.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.adapter.write_bytes_atomically(self.root, "snapshot.json", b"new-export")
        self.assertEqual(destination.read_bytes(), b"previous-valid-export")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".kira-transfer-")], [])


if __name__ == "__main__":
    unittest.main()
