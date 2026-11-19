"""T5-A File System Agent: real files in a temp folder, through the same registry the chat uses (path policy, intent guard, confirmation)."""
import json
import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from kira.tools import fileops
from kira.tools.access import PathPolicy
from kira.tools.builtin import build_registry
from kira.tools.fileagent import FileAgent, Journal, valid_name
from kira.tools.registry import OK, NEEDS_CONFIRM, DENIED, ERROR, BAD_ARGS, ToolError


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

    def test_reparse_points_are_treated_as_links(self):
        from types import SimpleNamespace
        from kira.tools.fileagent import _is_link_or_reparse

        with mock.patch("kira.tools.fileagent.os.path.islink", return_value=False), mock.patch(
            "kira.tools.fileagent.os.lstat", return_value=SimpleNamespace(st_file_attributes=0x400)
        ):
            self.assertTrue(_is_link_or_reparse(str(self.root / "junction")))

        with mock.patch("kira.tools.fileagent.os.path.islink", return_value=False), mock.patch(
            "kira.tools.fileagent.os.lstat", side_effect=PermissionError("metadata denied")
        ):
            self.assertTrue(_is_link_or_reparse(str(self.root / "unreadable")))

    def test_delete_folder_confirmation_discloses_incomplete_count(self):
        def partial_walk(root, followlinks=False, onerror=None):
            if onerror is not None:
                onerror(PermissionError("access denied"))
            yield str(root), [], []

        agent = FileAgent(self.policy, Journal(self.data))
        with mock.patch("kira.tools.fileagent.os.walk", side_effect=partial_walk):
            summary = agent.confirm_delete_folder({"path": str(self.root)})

        self.assertIn("شمارش 1 مورد", summary)
        self.assertIn("تعداد و حجم واقعی می‌تواند بیشتر باشد", summary)

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

    def test_sensitive_ancestor_names_are_blocked_at_any_depth(self):
        sensitive_root = self.root / "password-archive"
        nested = sensitive_root
        for index in range(10):
            nested = nested / f"level-{index}"
        nested.mkdir(parents=True)
        target = nested / "notes.txt"
        target.write_text("private", encoding="utf-8")

        with self.assertRaises(ToolError):
            self.policy.check(str(target))

    def test_list_folder_discloses_items_with_unreadable_metadata(self):
        target = self.root / "unreadable.txt"
        target.write_text("exists", encoding="utf-8")

        class FailingEntry:
            name = target.name
            path = str(target)

            @staticmethod
            def stat(follow_symlinks=False):
                raise PermissionError("metadata denied")

            @staticmethod
            def is_dir(follow_symlinks=False):
                return False

        with mock.patch.object(fileops.os, "scandir", return_value=[FailingEntry()]):
            result = fileops.FileTools(self.policy).list_folder({"path": str(self.root)})

        self.assertIn("فهرست ممکن است ناقص باشد", result)
        self.assertIn("1 مورد ناموفق", result)

    def test_list_folder_discloses_scandir_iterator_failure(self):
        (self.root / "visible.txt").write_text("visible", encoding="utf-8")
        real_scandir = os.scandir

        def failing_scandir(path):
            iterator = real_scandir(path)
            try:
                yield next(iterator)
                raise PermissionError("scan interrupted")
            finally:
                iterator.close()

        with mock.patch.object(fileops.os, "scandir", side_effect=failing_scandir):
            result = fileops.FileTools(self.policy).list_folder({"path": str(self.root)})

        self.assertIn("فهرست ممکن است ناقص باشد", result)
        self.assertIn("1 مورد ناموفق", result)

    def test_search_reports_skipped_inaccessible_folders(self):
        blocked = self.root / "blocked"
        blocked.mkdir()
        (blocked / "needle.txt").write_text("not visible to the scan", encoding="utf-8")
        real_scandir = os.scandir

        def guarded_scandir(path):
            if os.path.normcase(os.path.abspath(os.fspath(path))) == os.path.normcase(str(blocked)):
                raise PermissionError("access denied")
            return real_scandir(path)

        with mock.patch.object(fileops.os, "scandir", side_effect=guarded_scandir):
            result = fileops.FileTools(self.policy).search_files({"query": "needle"})

        self.assertIn("نتایج ممکن است ناقص باشند", result)
        self.assertIn("1 پوشه/مورد", result)

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

    def test_failed_file_copy_removes_partial_destination(self):
        source = self.root / "source.txt"
        source.write_text("source contents", encoding="utf-8")
        destination = self.root / "destination"
        destination.mkdir()
        target = destination / source.name

        def partial_copy(src, dst, length=0):
            dst.write(b"partial")
            raise OSError("simulated disk full")

        with mock.patch("kira.tools.fileagent.shutil.copyfileobj", side_effect=partial_copy):
            result = self.run_tool("copy_item", {"source": str(source), "destination_folder": str(destination)})

        self.assertEqual(result.status, ERROR)
        self.assertFalse(target.exists())

    def test_failed_folder_copy_removes_partial_destination(self):
        source = self.root / "source-folder"
        source.mkdir()
        (source / "first.txt").write_text("first", encoding="utf-8")
        destination = self.root / "destination"
        destination.mkdir()
        target = destination / source.name

        def partial_copy(_src, dst, **_kwargs):
            Path(dst, "partial.txt").write_text("partial", encoding="utf-8")
            raise shutil.Error("simulated mid-copy failure")

        with mock.patch("kira.tools.fileagent.shutil.copytree", side_effect=partial_copy):
            result = self.run_tool("copy_item", {"source": str(source), "destination_folder": str(destination)})

        self.assertEqual(result.status, ERROR)
        self.assertFalse(target.exists())

    def test_copy_rejects_executable_files_and_skips_them_in_folders(self):
        executable = self.root / "payload.exe"
        executable.write_bytes(b"MZ")
        destination = self.root / "copies"
        destination.mkdir()
        denied = self.run_tool("copy_item", {"source": str(executable), "destination_folder": str(destination)})
        self.assertEqual(denied.status, DENIED)
        self.assertFalse((destination / "payload.exe").exists())

        source = self.root / "mixed"
        source.mkdir()
        (source / "safe.txt").write_text("safe", encoding="utf-8")
        (source / "payload.bat").write_text("dangerous", encoding="utf-8")
        copied = self.run_tool("copy_item", {"source": str(source), "destination_folder": str(destination)})
        self.assertEqual(copied.status, OK, copied.text)
        self.assertTrue((destination / "mixed" / "safe.txt").exists())
        self.assertFalse((destination / "mixed" / "payload.bat").exists())
        self.assertIn("اجرایی رد شد", copied.text)

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

    def test_write_file_keeps_unique_backups_for_same_second_overwrites(self):
        target = self.root / "concurrent.txt"
        target.write_text("original", encoding="utf-8")

        with mock.patch("kira.tools.fileagent.time.strftime", return_value="20261119-120000"):
            first = self.sensitive("write_file", {"path": str(target), "content": "first"})
            self.assertEqual(first.status, OK, first.text)
            second = self.sensitive("write_file", {"path": str(target), "content": "second"})
            self.assertEqual(second.status, OK, second.text)

        backups = sorted(self.root.glob("concurrent.txt.bak-20261119-120000-*"))
        self.assertEqual(len(backups), 2)
        self.assertEqual({item.read_text(encoding="utf-8") for item in backups}, {"original", "first"})
        self.assertEqual(target.read_text(encoding="utf-8"), "second")
        self.assertFalse((self.root / "concurrent.txt.kira-tmp").exists())
        self.assertFalse(list(self.root.glob(".concurrent.txt.kira-*.tmp")))

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

    def test_organise_refuses_symlink_destination_outside_allowed_root(self):
        outside = Path(self.tmp.name, "outside")
        outside.mkdir()
        external_target = outside / "photo.jpg"
        (self.root / "photo.jpg").write_text("photo", encoding="utf-8")
        link = self.root / "Images"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")

        result = self.run_tool("organise_folder", {"folder": str(self.root)})
        self.assertNotEqual(result.status, OK)
        self.assertTrue((self.root / "photo.jpg").exists())
        self.assertFalse(external_target.exists())

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

    def test_undo_write_rejects_unrelated_file_inside_allowed_root_as_backup(self):
        target = self.root / "target.txt"
        unrelated = self.root / "unrelated.txt"
        target.write_text("current", encoding="utf-8")
        unrelated.write_text("unrelated content", encoding="utf-8")
        journal = Journal(self.data)
        journal.add("write", path=str(target), backup=str(unrelated))
        agent = FileAgent(self.policy, journal)

        with self.assertRaises(ToolError):
            agent.undo_last({})

        self.assertEqual(target.read_text(encoding="utf-8"), "current")

    def test_undo_write_restores_backup_when_target_was_deleted(self):
        target = self.root / "restore-after-delete.txt"
        target.write_text("original", encoding="utf-8")
        result = self.sensitive("write_file", {"path": str(target), "content": "replacement"})
        self.assertEqual(result.status, OK, result.text)
        target.unlink()

        undo = self.sensitive("undo_file_operation", {})
        self.assertEqual(undo.status, OK, undo.text)
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_undo_write_rejects_backup_outside_allowed_roots(self):
        target = self.root / "important.txt"
        target.write_text("current", encoding="utf-8")
        outside_backup = Path(self.tmp.name, "outside-backup.txt")
        outside_backup.write_text("attacker-controlled", encoding="utf-8")
        journal = Journal(self.data)
        journal.add("write", path=str(target), backup=str(outside_backup))
        agent = FileAgent(self.policy, journal)

        with self.assertRaises(ToolError):
            agent.undo_last({})

        self.assertEqual(target.read_text(encoding="utf-8"), "current")

    def test_undo_append_refuses_same_size_intervening_edits(self):
        target = self.root / "append-guard.txt"
        target.write_text("base", encoding="utf-8")
        appended = self.run_tool("append_text", {"path": str(target), "content": "tail"}, text="add tail")
        self.assertEqual(appended.status, OK, appended.text)
        expected_size = target.stat().st_size
        target.write_text("evil" + " " * (expected_size - 4), encoding="utf-8")
        modified = target.read_text(encoding="utf-8")

        undo = self.sensitive("undo_file_operation", {})
        self.assertEqual(undo.status, ERROR)
        self.assertEqual(target.read_text(encoding="utf-8"), modified)
        self.assertIn("محتوای فایل بعد از عملیات append تغییر کرده", undo.text)

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

    def test_journal_concurrent_adds_keep_valid_atomic_history(self):
        journal = Journal(self.data)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(
                lambda index: journal.add("create", path=f"file-{index}.txt"),
                range(80),
            ))

        persisted = json.loads((self.data / "kira_file_ops.json").read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 30)
        self.assertEqual(len({item["journal_id"] for item in persisted}), 30)
        self.assertEqual(len(journal.items), 30)
        self.assertFalse(list(self.data.glob(".kira_file_ops.json.*.tmp")))

    def test_file_operation_warns_when_journal_cannot_be_persisted(self):
        target = self.root / "journal-warning.txt"
        with mock.patch("kira.tools.fileagent.os.replace", side_effect=OSError("disk full")):
            result = self.run_tool("create_file", {"path": str(target), "content": "created"})

        self.assertEqual(result.status, OK, result.text)
        self.assertTrue(target.is_file())
        self.assertIn("Undo پس از بسته‌شدن برنامه تضمین‌شده نیست", result.text)

    def test_journal_reports_failed_persistence_for_add_and_undo_marker(self):
        journal = Journal(self.data)
        with mock.patch("kira.tools.fileagent.os.replace", side_effect=OSError("disk full")):
            self.assertFalse(journal.add("create", path=str(self.root / "x.txt")))
            item = journal.last()
            self.assertIsNotNone(item)
            self.assertFalse(journal.mark_undone(item))
        self.assertTrue(journal.last() is None)

    def test_catalog_gate_and_journal_persists(self):
        from kira.tools import protocol
        self.assertIn("files", protocol.detect_categories("این فایل را کپی کن"))
        self.run_tool("create_file", {"path": str(self.root / "j.txt")})
        from kira.tools.fileagent import Journal
        self.assertEqual(Journal(self.data).last()["op"], "create")


if __name__ == "__main__":
    unittest.main()
