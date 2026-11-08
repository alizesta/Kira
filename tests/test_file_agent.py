"""T5-A File System Agent: real files in a temp folder, through the same registry the chat uses (path policy, intent guard, confirmation)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira.tools import fileops
from kira.tools.access import PathPolicy
from kira.tools.builtin import build_registry
from kira.tools.fileagent import valid_name
from kira.tools.registry import OK, NEEDS_CONFIRM, DENIED, ERROR, BAD_ARGS


class FileAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name, "allowed")
        self.root.mkdir()
        self.data = Path(self.tmp.name, "data")
        self.data.mkdir()
        self.policy = PathPolicy({"tools_allowed_paths": [str(self.root)]}, self.data, None)
        self.reg = build_registry(self.policy)
        self.reg.user_text = "بساز و کپی کن create"
        trash = Path(self.tmp.name, "trash")
        trash.mkdir()

        def fake_recycle(path):                                     # the real one is the Windows shell API
            shutil.move(path, str(trash / (os.path.basename(path) + str(len(os.listdir(trash))))))
        for target in (fileops, __import__("kira.tools.fileagent", fromlist=["x"])):
            p = mock.patch.object(target, "_recycle", fake_recycle)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("sys.platform", "win32")                       # delete paths only run on Windows; the recycle call itself is faked
        p.start()
        self.addCleanup(p.stop)

    def run_tool(self, name, args, confirmed=False, text=None):
        if text is not None:
            self.reg.user_text = text
        return self.reg.execute(name, args, confirmed=confirmed)

    def sensitive(self, name, args):
        first = self.run_tool(name, args)
        self.assertEqual(first.status, NEEDS_CONFIRM, first.text)
        self.reg.user_text = "تأیید"
        return self.reg.execute(name, first.args, confirmed=True)

    def test_create_folder_and_file_never_overwrite(self):
        d = str(self.root / "گزارش آبان")
        self.assertEqual(self.run_tool("make_folder", {"path": d}).status, OK)
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(self.run_tool("make_folder", {"path": d}).status, ERROR)           # exists
        f = os.path.join(d, "note.txt")
        res = self.run_tool("create_file", {"path": f, "content": "سلام"})
        self.assertEqual(res.status, OK, res.text)
        self.assertEqual(Path(f).read_text(encoding="utf-8"), "سلام")
        again = self.run_tool("create_file", {"path": f, "content": "other"})
        self.assertEqual(again.status, ERROR)
        self.assertEqual(Path(f).read_text(encoding="utf-8"), "سلام")                         # untouched

    def test_requires_user_intent_and_blocks_scripts_secrets_and_outside_paths(self):
        f = str(self.root / "a.txt")
        self.assertEqual(self.run_tool("create_file", {"path": f}, text="what time is it").status, DENIED)
        self.assertFalse(os.path.exists(f))
        for bad in ("run.bat", "x.ps1", "tool.exe", "CON.txt", "bad:name.txt", "end."):
            self.assertNotEqual(self.run_tool("create_file", {"path": str(self.root / bad)}, text="create it").status, OK, bad)
        self.assertNotEqual(self.run_tool("create_file", {"path": str(self.root / "my_password.txt")}, text="create it").status, OK)
        outside = str(Path(self.tmp.name) / "outside.txt")
        self.assertEqual(self.run_tool("create_file", {"path": outside}, text="create it").status, DENIED)
        self.assertEqual(self.run_tool("create_file", {"path": str(self.root / ".." / "x.txt")}, text="create it").status, DENIED)

    def test_copy_file_and_folder_rename_and_no_overwrite(self):
        src = self.root / "src"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "a.txt").write_text("A")
        (src / "keys.pem").write_text("secret")                                              # sensitive names are not copied
        dest = self.root / "dest"
        dest.mkdir()
        res = self.run_tool("copy_item", {"source": str(src), "destination_folder": str(dest)})
        self.assertEqual(res.status, OK, res.text)
        self.assertTrue((dest / "src" / "sub" / "a.txt").exists())
        self.assertFalse((dest / "src" / "keys.pem").exists())
        self.assertEqual(self.run_tool("copy_item", {"source": str(src), "destination_folder": str(dest)}).status, ERROR)   # exists
        self.assertEqual(self.run_tool("copy_item", {"source": str(src), "destination_folder": str(src)}).status, ERROR)    # into itself
        f = self.root / "r.txt"
        f.write_text("x")
        self.assertEqual(self.run_tool("rename_item", {"path": str(f), "new_name": "r2.txt"}).status, OK)
        self.assertTrue((self.root / "r2.txt").exists() and not f.exists())
        self.assertNotEqual(self.run_tool("rename_item", {"path": str(self.root / "r2.txt"), "new_name": "r2.bat"}).status, OK)
        self.assertNotEqual(self.run_tool("rename_item", {"path": str(self.root / "r2.txt"), "new_name": "sub/x.txt"}).status, OK)

    def test_append_only_plain_text_and_write_replaces_with_backup(self):
        f = self.root / "n.txt"
        f.write_text("one")
        self.assertEqual(self.run_tool("append_text", {"path": str(f), "content": "two"}, text="add this").status, OK)
        self.assertEqual(f.read_text(), "one\ntwo")
        docx = self.root / "d.docx"
        docx.write_bytes(b"PK")
        self.assertEqual(self.run_tool("append_text", {"path": str(docx), "content": "x"}, text="add this").status, ERROR)
        res = self.sensitive("write_file", {"path": str(f), "content": "new"})
        self.assertEqual(res.status, OK, res.text)
        self.assertEqual(f.read_text(), "new")
        backups = [p for p in self.root.iterdir() if ".bak-" in p.name]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "one\ntwo")
        self.assertEqual(self.run_tool("write_file", {"path": str(self.root / "x.bat"), "content": "x"}).status, DENIED)

    def test_batch_is_all_or_nothing_on_conflicts_and_needs_confirmation(self):
        a, b = self.root / "a.txt", self.root / "b.txt"
        a.write_text("1")
        b.write_text("2")
        dest = self.root / "out"
        dest.mkdir()
        (dest / "b.txt").write_text("existing")
        bad = self.run_tool("batch_files", {"operation": "move", "paths": [str(a), str(b)], "destination_folder": str(dest)})
        self.assertEqual(bad.status, ERROR)
        self.assertTrue(a.exists() and b.exists())                                          # nothing moved
        (dest / "b.txt").unlink()
        res = self.sensitive("batch_files", {"operation": "copy", "paths": [str(a), str(b)], "destination_folder": str(dest)})
        self.assertEqual(res.status, OK, res.text)
        self.assertTrue((dest / "a.txt").exists() and (dest / "b.txt").exists() and a.exists())
        res = self.sensitive("batch_files", {"operation": "delete", "paths": [str(a), str(b)]})
        self.assertEqual(res.status, OK, res.text)
        self.assertFalse(a.exists() or b.exists())
        self.assertEqual(self.run_tool("batch_files", {"operation": "delete", "paths": [str(r) for r in self.policy.roots()[:1]]}).status, DENIED)

    def test_delete_folder_and_protected_roots(self):
        d = self.root / "old"
        d.mkdir()
        (d / "f.txt").write_text("x")
        res = self.sensitive("delete_folder", {"path": str(d)})
        self.assertEqual(res.status, OK, res.text)
        self.assertFalse(d.exists())
        self.assertEqual(self.run_tool("delete_folder", {"path": str(self.root)}).status, DENIED)

    def test_organise_by_type_and_undo(self):
        for n in ("a.jpg", "b.pdf", "c.mp3", "d.xyz"):
            (self.root / n).write_text("x")
        res = self.sensitive("organise_folder", {"folder": str(self.root)})
        self.assertEqual(res.status, OK, res.text)
        self.assertTrue((self.root / "Images" / "a.jpg").exists() and (self.root / "Documents" / "b.pdf").exists() and (self.root / "Other" / "d.xyz").exists())
        undo = self.sensitive("undo_file_operation", {})
        self.assertEqual(undo.status, OK, undo.text)
        self.assertTrue(all((self.root / n).exists() for n in ("a.jpg", "b.pdf", "c.mp3", "d.xyz")))               # the WHOLE operation went back
        self.assertFalse((self.root / "Other" / "d.xyz").exists())

    def test_undo_create_rename_append(self):
        f = self.root / "u.txt"
        self.run_tool("create_file", {"path": str(f), "content": "base"})
        self.run_tool("append_text", {"path": str(f), "content": "+more"}, text="add it")
        self.assertEqual(self.sensitive("undo_file_operation", {}).status, OK)
        self.assertEqual(f.read_text(), "base")
        self.run_tool("rename_item", {"path": str(f), "new_name": "v.txt"}, text="rename it")
        self.assertEqual(self.sensitive("undo_file_operation", {}).status, OK)
        self.assertTrue(f.exists())
        self.assertEqual(self.sensitive("undo_file_operation", {}).status, OK)                # undoes the create (to the fake recycle bin)
        self.assertFalse(f.exists())

    def test_valid_name_rules(self):
        from kira.tools.registry import ToolError
        self.assertEqual(valid_name("گزارش آبان.docx"), "گزارش آبان.docx")
        for bad in ("", "..", "a/b", "a*b", "nul", "x.exe", "a|b"):
            with self.assertRaises(ToolError):
                valid_name(bad)

    def test_catalog_gate_and_journal_persists(self):
        from kira.tools import protocol
        self.assertIn("files", protocol.detect_categories("این فایل را کپی کن"))
        self.run_tool("create_file", {"path": str(self.root / "j.txt")})
        from kira.tools.fileagent import Journal
        self.assertEqual(Journal(self.data).last()["op"], "create")


if __name__ == "__main__":
    unittest.main()
