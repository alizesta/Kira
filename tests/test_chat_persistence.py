"""Task 02: chat history is saved, survives restarts, survives database problems and cannot be deleted by accident."""
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import helpers
from tests.helpers import StreamResp, sse

from kira import memory, storage, config

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QCoreApplication
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False
if HAVE_QT:
    APP = QApplication.instance() or QApplication([])


class IsolatedDb(unittest.TestCase):
    """Every test gets its own empty database folder (memory.DB_PATH is patched; the user's real data is never touched)."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="kira_chat_"))
        self.db = self.dir / "kira_memory.sqlite3"
        self.patch = mock.patch.object(memory, "DB_PATH", self.db)
        self.patch.start()
        memory._pending.clear()
        memory.last_error = None
        memory.init_db()

    def tearDown(self):
        self.patch.stop()
        memory._pending.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def texts(self, limit=1000):
        return [m["content"] for m in memory.recent_messages(limit)]

    def fill(self, n, prefix="m"):
        for i in range(n):
            self.assertTrue(memory.add_message("user" if i % 2 == 0 else "assistant", f"{prefix}{i}"))


class SaveAndRestoreTests(IsolatedDb):
    def test_messages_survive_a_restart_in_order_with_persian_and_emoji(self):
        memory.add_message("user", "سلام کیرا 👋")
        memory.add_message("assistant", "[happy]\nسلام! چطوری؟")
        memory.init_db()                                                      # a restart opens the same file again
        self.assertEqual(self.texts(), ["سلام کیرا 👋", "[happy]\nسلام! چطوری؟"])
        memory.add_message("user", "x" * 50000)                                  # very long text is stored whole
        self.assertEqual(len(self.texts()[-1]), 50000)

    def test_every_connection_is_closed(self):
        opened, closed = [], []
        real = sqlite3.connect

        class Tracked:
            def __init__(self, *a, **k):
                self.con = real(*a, **k)
                opened.append(1)

            def __getattr__(self, name):
                return getattr(self.con, name)

            def __enter__(self):
                return self.con.__enter__()

            def __exit__(self, *a):
                return self.con.__exit__(*a)

            def close(self):
                closed.append(1)
                self.con.close()
        with mock.patch("kira.memory.sqlite3.connect", Tracked):
            memory.add_message("user", "a")
            memory.recent_messages(5)
            memory.message_count()
        self.assertTrue(opened and len(opened) == len(closed))

    def test_concurrent_saves_lose_nothing(self):
        errors = []

        def worker(k):
            for i in range(40):
                if not memory.add_message("user", f"t{k}-{i}"):
                    errors.append((k, i))
        threads = [threading.Thread(target=worker, args=(k,)) for k in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(memory.message_count(), 200)


class DatabaseErrorTests(IsolatedDb):
    def test_locked_database_keeps_messages_in_memory_then_flushes_in_order(self):
        self.fill(2)
        with mock.patch.object(memory, "_db", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertFalse(memory.add_message("user", "p1"))
            self.assertFalse(memory.add_message("assistant", "p2"))
            self.assertEqual(memory.pending_count(), 2)
            self.assertEqual(self.texts(), ["p1", "p2"])                        # chat context still works from memory
            self.assertIn("locked", memory.last_error)
        self.assertTrue(memory.add_message("user", "p3"))                      # disk is back: everything is written
        self.assertEqual(self.texts(), ["m0", "m1", "p1", "p2", "p3"])
        self.assertEqual(memory.pending_count(), 0)
        self.assertIsNone(memory.last_error)

    def test_garbage_file_is_quarantined_never_deleted_and_a_fresh_db_is_created(self):
        self.fill(3)
        self.db.write_bytes(b"this is not a sqlite database" * 100)
        garbage = self.db.read_bytes()
        notes = memory.init_db()
        self.assertTrue(notes and "خراب" in notes[0])
        kept = list(self.dir.glob("kira_memory.corrupt-*.sqlite3"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), garbage)                        # the damaged file is kept byte for byte
        self.assertTrue(memory.add_message("user", "after recovery"))
        self.assertEqual(self.texts(), ["after recovery"])

    def test_recovery_rebuilds_from_the_newest_valid_backup(self):
        self.fill(30)
        self.assertIsNotNone(storage.backup_user_data(self.dir, min_age_hours=0))
        memory.add_message("user", "newer than the backup")
        self.db.write_bytes(b"\x00" * 4096)
        notes = memory.init_db()
        self.assertTrue(notes)
        self.assertEqual(memory.message_count(), 30)                           # everything the backup had
        self.assertEqual(self.texts(3), ["m27", "m28", "m29"])
        self.assertIn("پشتیبان", notes[0])

    def test_partially_damaged_file_salvages_readable_rows_and_merges_with_backup(self):
        self.fill(200)
        storage.backup_user_data(self.dir, min_age_hours=0)
        self.fill(20, "late")
        size = self.db.stat().st_size
        data = bytearray(self.db.read_bytes())
        data[size // 2: size // 2 + 4096] = b"\xff" * 4096                       # damage a page in the middle
        self.db.write_bytes(bytes(data))
        memory.init_db()
        self.assertGreaterEqual(memory.message_count(), 200)
        self.assertEqual(len(list(self.dir.glob("kira_memory.corrupt-*"))), 1)

    def test_corruption_found_while_chatting_is_recovered_and_the_message_is_saved(self):
        self.fill(4)
        storage.backup_user_data(self.dir, min_age_hours=0)
        self.db.write_bytes(b"junk" * 2000)
        self.assertTrue(memory.add_message("user", "typed after the file broke"))
        self.assertIn("typed after the file broke", self.texts())
        self.assertEqual(memory.message_count(), 5)
        self.assertTrue(memory.startup_notes)

    def test_unwritable_folder_never_raises_into_the_app(self):
        with mock.patch.object(memory, "_db", side_effect=OSError("disk full")):
            self.assertEqual(memory.init_db()[0].startswith("دیتابیس گفتگو باز نشد"), True)
            self.assertFalse(memory.add_message("user", "x"))
            self.assertEqual(memory.recent_messages(3), [{"role": "user", "content": "x"}])
            self.assertEqual(memory.conversation_context(3), [{"role": "user", "content": "x"}])
            self.assertEqual(memory.message_count(), 0)


class ClearRestoreImportTests(IsolatedDb):
    def test_clear_saves_a_snapshot_and_restore_brings_everything_back_in_order(self):
        self.fill(10)
        memory.clear_memory()
        self.assertEqual(memory.message_count(), 0)
        self.assertEqual(len(memory.list_snapshots("cleared")), 1)
        self.assertEqual(memory.restore_last_cleared(), 10)
        self.assertEqual(self.texts(), [f"m{i}" for i in range(10)])
        self.assertEqual(memory.restore_last_cleared(), 0)                      # idempotent: no duplicates

    def test_clear_is_refused_when_the_snapshot_cannot_be_made(self):
        self.fill(5)
        with mock.patch.object(memory, "_snapshot", side_effect=OSError("no space")):
            with self.assertRaises(memory.ChatStoreError):
                memory.clear_memory()
        self.assertEqual(memory.message_count(), 5)                             # nothing was deleted

    def test_clear_of_empty_history_makes_no_snapshot_and_old_snapshots_are_bounded(self):
        memory.clear_memory()
        self.assertEqual(memory.list_snapshots("cleared"), [])
        for i in range(8):
            memory.add_message("user", f"x{i}")
            memory.clear_memory()
            time.sleep(0.02)
        self.assertLessEqual(len(memory.list_snapshots("cleared")), memory.SNAPSHOTS_KEEP)

    def test_restore_without_any_clear_is_a_clear_error(self):
        with self.assertRaises(memory.ChatStoreError):
            memory.restore_last_cleared()

    def test_import_merges_old_chat_chronologically_without_duplicates(self):
        old = self.dir / "old" / "kira_memory.sqlite3"
        old.parent.mkdir()
        con = sqlite3.connect(old)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP)")
        con.executemany("INSERT INTO messages(role, content, created_at) VALUES (?,?,?)",
                        [("user", "old-1", "2025-01-01 10:00:00"), ("assistant", "old-2", "2025-01-01 10:00:05"),
                         ("user", "shared", "2025-06-01 09:00:00")])
        con.commit()
        con.close()
        with memory._db() as c:
            c.executemany("INSERT INTO messages(role, content, created_at) VALUES (?,?,?)",
                          [("user", "shared", "2025-06-01 09:00:00"), ("assistant", "new-1", "2025-06-01 09:00:03")])
        self.assertEqual(memory.import_messages(old), 2)
        self.assertEqual(self.texts(), ["old-1", "old-2", "shared", "new-1"])
        self.assertEqual(memory.import_messages(old), 0)                         # running it twice changes nothing
        self.assertEqual(len(memory.list_snapshots("before-import")), 1)          # safety snapshot of the current chat
        with self.assertRaises(memory.ChatStoreError):
            memory.import_messages(self.dir / "missing.sqlite3")

    def test_failed_write_rolls_back_completely(self):
        self.fill(6)
        bad = [("user", "ok", "2025-01-01 00:00:00"), (None, "role is NOT NULL -> error", "2025-01-01 00:00:01")]
        with self.assertRaises(sqlite3.Error):
            memory._write_all(bad)
        self.assertEqual(self.texts(), [f"m{i}" for i in range(6)])               # the old content is untouched


class MigrationGapTests(unittest.TestCase):
    def test_settings_already_present_but_no_chat_database_still_gets_the_old_chat(self):
        tmp = Path(tempfile.mkdtemp(prefix="kira_mig_"))
        old = tmp / "Project_Kira_old" / "data"
        old.mkdir(parents=True)
        (old / storage.SETTINGS_NAME).write_text("OLD", encoding="utf-8")
        con = sqlite3.connect(old / storage.DB_NAME)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)")
        con.execute("INSERT INTO messages(role, content) VALUES ('user','old chat')")
        con.commit()
        con.close()
        new = tmp / "Local" / "Kira"
        new.mkdir(parents=True)
        (new / storage.SETTINGS_NAME).write_text("NEW-SETTINGS", encoding="utf-8")        # e.g. created by a version run earlier
        note = storage.migrate_legacy(new, [old])
        self.assertIn(storage.DB_NAME, note)
        self.assertEqual((new / storage.SETTINGS_NAME).read_text(encoding="utf-8"), "NEW-SETTINGS")   # never overwritten
        self.assertEqual(sqlite3.connect(new / storage.DB_NAME).execute("SELECT content FROM messages").fetchall(), [("old chat",)])
        self.assertIsNone(storage.migrate_legacy(new, [old]))                              # one time only
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowPersistenceTests(IsolatedDb):
    def setUp(self):
        super().setUp()
        d = Path(tempfile.mkdtemp(prefix="kira_cfg_"))
        self.cfgdir = d
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", d / "settings.json"),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot),
                        mock.patch("requests.get", side_effect=__import__("requests").ConnectionError("off"))]
        for p in self.patches:
            p.start()
        self.windows = []
        self.win = self.open_window()

    def open_window(self):
        from kira.main import MainWindow, STYLE
        APP.setStyleSheet(STYLE)
        w = MainWindow()
        w.show()
        w.set_voice_enabled(False)
        helpers.enable(w.settings, "groq")
        w.settings["providers"]["ollama"]["enabled"] = False
        from kira import routes
        from kira.hybrid_ai import HybridRouter
        routes.ensure_routes(w.settings)
        w.client = HybridRouter(w.settings)
        APP.processEvents()
        self.windows.append(w)
        return w

    def tearDown(self):
        for w in self.windows:
            try:
                w.client.cancel()
                if getattr(w, "worker", None) is not None:
                    w.worker.wait(3000)
                w.companion.close()
                w.close()
            except RuntimeError:
                pass
        APP.processEvents()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.cfgdir, ignore_errors=True)
        super().tearDown()

    def send(self, w, text, reply="پاسخ"):
        with mock.patch("requests.post", side_effect=lambda *a, **k: StreamResp(sse(reply))):
            w.input.setText(text)
            w.send_message()
            end = time.time() + 8
            while time.time() < end and w.busy:
                QCoreApplication.processEvents()
                time.sleep(0.01)
        self.assertFalse(w.busy)

    def test_chat_is_back_after_closing_and_reopening_the_app(self):
        self.send(self.win, "سوال اول", "جواب اول")
        self.send(self.win, "سوال دوم", "جواب دوم")
        self.win.companion.close()
        self.win.close()
        w2 = self.open_window()
        text = w2.chat.toPlainText()
        for part in ("سوال اول", "جواب اول", "سوال دوم", "جواب دوم"):
            self.assertEqual(text.count(part), 1, part)
        self.assertLess(text.index("جواب اول"), text.index("سوال دوم"))
        self.assertNotIn("[happy]", text)

    def test_disk_failure_does_not_block_chat_warns_once_and_catches_up(self):
        w = self.win
        with mock.patch.object(memory, "_db", side_effect=sqlite3.OperationalError("database is locked")):
            self.send(w, "یک", "الف")
            self.send(w, "دو", "ب")
            text = w.chat.toPlainText()
            self.assertIn("الف", text)
            self.assertIn("ب", text)                                          # answers were still shown
            self.assertEqual(text.count("ذخیره‌ی گفتگو روی دیسک ناموفق بود"), 1)  # warned once, not on every message
        self.send(w, "سه", "ج")                                                # disk is back
        self.assertEqual(memory.pending_count(), 0)
        self.assertEqual(self.texts(), ["یک", "الف", "دو", "ب", "سه", "ج"])    # nothing lost, order kept
        self.assertFalse(w._save_warned)

    def test_window_starts_with_a_damaged_database_and_reports_the_recovery(self):
        self.send(self.win, "قدیمی", "پاسخ قدیمی")
        storage.backup_user_data(self.dir, min_age_hours=0)
        self.win.companion.close()
        self.win.close()
        self.db.write_bytes(b"broken" * 1000)
        w2 = self.open_window()
        text = w2.chat.toPlainText()
        self.assertIn("خراب بود", text)
        self.assertIn("قدیمی", text)                                            # history rebuilt from the backup
        self.send(w2, "ادامه", "ادامه یافت")
        self.assertIn("ادامه یافت", w2.chat.toPlainText())

    def test_clear_and_restore_buttons(self):
        w = self.win
        self.send(w, "پیام مهم", "پاسخ مهم")
        with mock.patch("kira.main.QMessageBox.question", return_value=QMessageBox.Yes):
            w.clear_chat()
        self.assertEqual(memory.message_count(), 0)
        self.assertNotIn("پیام مهم", w.chat.toPlainText().replace("بازگرداندن", ""))
        w.restore_chat_btn.click()
        self.assertIn("پیام مهم", w.chat.toPlainText())
        self.assertEqual(memory.message_count(), 2)

    def test_clear_answer_no_deletes_nothing_and_failed_snapshot_blocks_clear(self):
        w = self.win
        self.send(w, "نگه دار", "باشه")
        with mock.patch("kira.main.QMessageBox.question", return_value=QMessageBox.No):
            w.clear_chat()
        self.assertEqual(memory.message_count(), 2)
        with mock.patch("kira.main.QMessageBox.question", return_value=QMessageBox.Yes), \
                mock.patch.object(memory, "_snapshot", side_effect=OSError("no space")), \
                mock.patch("kira.main.QMessageBox.warning") as warn:
            w.clear_chat()
        warn.assert_called_once()
        self.assertEqual(memory.message_count(), 2)
        self.assertIn("نگه دار", w.chat.toPlainText())

    def test_import_old_chat_button_path(self):
        old = self.dir / "legacy.sqlite3"
        con = sqlite3.connect(old)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT)")
        con.execute("INSERT INTO messages(role, content, created_at) VALUES ('user','چت نسخه قدیمی','2024-01-01 00:00:00')")
        con.commit()
        con.close()
        self.win.import_old_chat(str(old))
        self.assertIn("چت نسخه قدیمی", self.win.chat.toPlainText())
        self.assertEqual(self.texts(), ["چت نسخه قدیمی"])

    def test_closing_the_window_mid_answer_keeps_the_partial_reply(self):
        w = self.win
        gate = threading.Event()
        lines = sse("نیمه‌ی پاسخ", done=False) + [lambda: gate.wait(5)] + sse(" بقیه")
        with mock.patch("requests.post", side_effect=lambda *a, **k: StreamResp(list(lines))):
            w.input.setText("سوال")
            w.send_message()
            end = time.time() + 6
            while time.time() < end and "نیمه‌ی پاسخ" not in w.chat.toPlainText():
                QCoreApplication.processEvents()
                time.sleep(0.01)
            w.companion.close()
            w.close()
            gate.set()
            w.worker.wait(3000)
            QCoreApplication.processEvents()
        self.assertEqual(self.texts(), ["سوال", "نیمه‌ی پاسخ"])                  # saved once, no late duplicate

    def test_error_while_starting_a_request_never_leaves_the_window_busy(self):
        w = self.win
        with mock.patch("kira.main.conversation_context", side_effect=RuntimeError("history exploded")):
            w.input.setText("hi")
            w.send_message()
        self.assertFalse(w.busy)
        self.assertTrue(w.send_btn.isEnabled())
        self.assertIn("history exploded", w.chat.toPlainText())
        self.send(w, "دوباره", "کار می‌کند")
        self.assertIn("کار می‌کند", w.chat.toPlainText())


if __name__ == "__main__":
    unittest.main()
