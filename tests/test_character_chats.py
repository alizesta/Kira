"""Per-character chats: separate saved history, independent chat sessions, character themes."""
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kira import memory, theme, chat_sessions, chat_render

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False
if HAVE_QT:
    APP = QApplication.instance() or QApplication([])


class IsolatedDb(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="kira_chars_"))
        self.db = self.dir / "kira_memory.sqlite3"
        self.patch = mock.patch.object(memory, "DB_PATH", self.db)
        self.patch.start()
        memory._pending.clear()
        memory.init_db()

    def tearDown(self):
        self.patch.stop()


class PerCharacterHistoryTests(IsolatedDb):
    def test_each_character_has_its_own_history(self):
        memory.add_message("user", "salam kira")                      # no character given = Kira (old behaviour)
        memory.add_message("user", "hi ren", "ren")
        memory.add_message("assistant", "hello", "ren")
        memory.add_message("user", "hi mika", "mika")
        self.assertEqual([m["content"] for m in memory.recent_messages(10, "kira")], ["salam kira"])
        self.assertEqual([m["content"] for m in memory.recent_messages(10, "ren")], ["hi ren", "hello"])
        self.assertEqual([m["content"] for m in memory.recent_messages(10, "mika")], ["hi mika"])
        self.assertEqual(len(memory.recent_messages(10)), 4)         # no character = every chat (old shared view)
        self.assertEqual(memory.message_count("ren"), 2)
        self.assertEqual([m["content"] for m in memory.conversation_context(10, character_id="mika")], ["hi mika"])

    def test_old_database_without_character_column_is_migrated_to_kira(self):
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO messages(role, content) VALUES ('user', 'old message')")
        con.commit()
        con.close()
        memory.init_db()
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "kira")], ["old message"])
        self.assertTrue(memory.add_message("user", "new for ren", "ren"))
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "ren")], ["new for ren"])
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "kira")], ["old message"])

    def test_clear_one_character_keeps_the_others_and_restore_keeps_ownership(self):
        memory.add_message("user", "k1")
        memory.add_message("user", "r1", "ren")
        memory.add_message("user", "m1", "mika")
        memory.clear_memory("ren")
        self.assertEqual(memory.recent_messages(5, "ren"), [])
        self.assertEqual(memory.message_count(), 2)
        self.assertEqual(memory.restore_last_cleared(), 1)
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "ren")], ["r1"])
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "mika")], ["m1"])

    def test_messages_kept_in_memory_while_database_is_down_keep_their_owner(self):
        with mock.patch.object(memory.repository, "_db", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertFalse(memory.add_message("user", "pending ren", "ren"))
            self.assertFalse(memory.add_message("user", "pending mika", "mika"))
            self.assertEqual([m["content"] for m in memory.recent_messages(5, "ren")], ["pending ren"])
        self.assertTrue(memory.add_message("user", "after", "ren"))
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "ren")], ["pending ren", "after"])
        self.assertEqual([m["content"] for m in memory.recent_messages(5, "mika")], ["pending mika"])

    def test_recovery_after_corruption_keeps_character_ownership(self):
        memory.add_message("user", "ren before", "ren")
        memory.add_message("user", "kira before")
        rows = memory.read_rows_full(self.db)
        self.assertEqual({r[3] for r in rows}, {"ren", "kira"})
        merged = memory._merge(rows, rows)
        self.assertEqual(len(merged), 2)                              # duplicates (same owner) are still removed


class SessionHelperTests(unittest.TestCase):
    def test_sessions_keep_request_identity_separate(self):
        a, b = chat_sessions.ChatSession("ren"), chat_sessions.ChatSession("mika")
        a.busy = True
        a.application_request_id = "ren-request"
        self.assertFalse(b.busy)
        self.assertIsNone(b.application_request_id)
        self.assertEqual(a.application_request_id, "ren-request")

    def test_each_chat_session_retains_its_own_persisted_conversation_id(self):
        kira = chat_sessions.ChatSession("kira")
        ren = chat_sessions.ChatSession("ren")
        mika = chat_sessions.ChatSession("mika")
        kira.conversation_id = "conversation-kira"
        ren.conversation_id = "conversation-ren"
        mika.conversation_id = "conversation-mika"

        self.assertEqual(
            {kira.conversation_id, ren.conversation_id, mika.conversation_id},
            {"conversation-kira", "conversation-ren", "conversation-mika"},
        )
        self.assertIsNone(chat_sessions.ChatSession("ren").conversation_id)

    def test_front_only_objects_are_silent_for_background_chats(self):
        class Voice:
            def stop(self):
                raise AssertionError("a background chat must not touch the voice")

        class Window:
            speaker = chat_sessions.front_only_property("speaker")
            busy = chat_sessions.session_property("busy")

        w = Window()
        front, back = chat_sessions.ChatSession("kira"), chat_sessions.ChatSession("ren")
        w.front = w.cur = front
        w.speaker = Voice()
        front.busy, back.busy = False, True
        with self.assertRaises(AssertionError):
            w.speaker.stop()
        w.cur = back
        self.assertIsNone(w.speaker.stop())                           # swallowed
        self.assertFalse(w.speaker)                                   # and falsy: "if self.speaker._began" is False
        self.assertTrue(w.busy)
        w.cur = front
        self.assertFalse(w.busy)


class ThemeTests(unittest.TestCase):
    def test_every_builtin_character_has_its_own_glass_neon_theme(self):
        seen = set()
        for cid in ("kira", "ren", "mika"):
            t = theme.character_theme(cid)
            css = theme.character_style(t, "acrylic")
            self.assertIn("QFrame#chatCard", css)
            self.assertIn("rgba(", css)                               # translucent = glass
            self.assertIn(t["main"].lstrip("#") and "QPushButton#charTab:checked", css)
            seen.add(t["main"])
        self.assertEqual(len(seen), 3)

    def test_custom_character_colour_and_fallback(self):
        t = theme.character_theme("custom_1", {"theme_color": "#33AA66"})
        self.assertEqual(t["main"], "#33AA66")
        self.assertEqual(theme.character_theme("unknown")["main"], theme.CHARACTER_THEMES["kira"]["main"])
        self.assertEqual(theme.character_theme("x", {"theme_color": "bad"})["main"], theme.CHARACTER_THEMES["kira"]["main"])

    def test_assistant_bubble_takes_the_character_tint(self):
        html = chat_render.message_html("assistant", "Ren", "hi", accent={"bubble": "#3A1620", "name": "#FF9AA5"})
        self.assertIn("#3A1620", html)
        self.assertNotIn("#3A1620", chat_render.message_html("user", "me", "hi", accent={"bubble": "#3A1620", "name": "#FF9AA5"}))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiSessionTests(IsolatedDb):
    def setUp(self):
        super().setUp()
        from kira import config
        from tests import helpers
        d = Path(tempfile.mkdtemp(prefix="kira_gui_chars_"))
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", d / "settings.json"),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot),
                        mock.patch("requests.get", side_effect=OSError("offline"))]
        for p in self.patches:
            p.start()
        memory.add_message("user", "پیام قدیمی رن", "ren")
        from kira.ui.main_window import MainWindow
        self.win = MainWindow()
        self.win.show()
        APP.processEvents()

    def tearDown(self):
        self.win.speaker.stop()
        self.win.companion.close()
        self.win.close()
        APP.processEvents()
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_three_tabs_with_separate_conversations_and_themes(self):
        w = self.win
        self.assertTrue({"kira", "ren", "mika"} <= set(w.sessions))
        self.assertTrue({"kira", "ren", "mika"} <= set(w.char_tab_buttons))
        self.assertNotIn("پیام قدیمی رن", w.sessions["kira"].view.toPlainText())
        self.assertIn("پیام قدیمی رن", w.sessions["ren"].view.toPlainText())
        w.switch_session("ren")
        self.assertIs(w.front, w.sessions["ren"])
        self.assertEqual(w.settings["active_character_id"], "ren")
        self.assertIs(w.chat_stack.currentWidget(), w.sessions["ren"].view)
        self.assertIn("rgba(255,77,94", w.chat_page.styleSheet())     # Ren's colours
        w.switch_session("mika")
        self.assertIn("rgba(255,111,198", w.chat_page.styleSheet())   # Mika's colours

    def test_background_chat_works_independently_and_stays_silent(self):
        w = self.win
        w.switch_session("kira")
        ren = w.sessions["ren"]
        ren.busy = True
        self.assertFalse(w.busy)                                      # Kira (in front) is not busy while Ren is
        with w._as(ren):
            self.assertTrue(w.busy)
            self.assertFalse(w.status)                                # status line / voice / face are muted for background chats
            self.assertFalse(w.speaker)
            w.add_chat("assistant", "جواب رن")
            w.save_message("assistant", "جواب رن")
            self.assertEqual(w.settings["active_character_id"], "ren")
        self.assertEqual(w.settings["active_character_id"], "kira")   # restored
        self.assertIn("جواب رن", ren.view.toPlainText())
        self.assertNotIn("جواب رن", w.sessions["kira"].view.toPlainText())
        self.assertEqual(memory.recent_messages(5, "ren")[-1]["content"], "جواب رن")
        self.assertNotIn("جواب رن", [m["content"] for m in memory.recent_messages(20, "kira")])
        ren.busy = False

    def test_concurrent_session_completions_drain_their_own_queues_after_tab_switch(self):
        w = self.win
        scheduled = []
        dispatched = []
        w.chat_application_service._schedule = scheduled.append
        w._process_chat_request = lambda text, _attachments, _voice: dispatched.append(
            (w.cur.cid, text, w.front.cid)
        )
        ren_active = w.chat_application_service.submit_message("ren", "Ren active")
        mika_active = w.chat_application_service.submit_message("mika", "Mika active")
        w.chat_application_service.submit_message("ren", "Ren queued", busy=True)
        w.chat_application_service.submit_message("mika", "Mika queued", busy=True)

        w.chat_application_service.complete_local_request(ren_active.request.request_id)
        w._send_next_pending(w.sessions["ren"])
        w.chat_application_service.complete_local_request(mika_active.request.request_id)
        w._send_next_pending(w.sessions["mika"])
        w.switch_session("kira")  # switch tabs before the queued callbacks execute

        self.assertEqual(len(scheduled), 2)
        for callback in list(scheduled):
            callback()
        self.assertEqual(
            dispatched,
            [
                ("ren", "Ren active", "kira"),
                ("mika", "Mika active", "kira"),
                ("ren", "Ren queued", "kira"),
                ("mika", "Mika queued", "kira"),
            ],
        )
        self.assertEqual(w.cur.cid, "kira")

    def test_submit_queues_behind_a_request_already_reserved_for_dispatch(self):
        w = self.win
        ren = w.sessions["ren"]
        w.chat_application_service._dispatch_scheduled.add("ren")
        with w._as(ren):
            w.submit("message after reserved queue item")
        self.assertEqual(w.chat_application_service.pending_count("ren"), 1)
        w.chat_application_service._dispatch_scheduled.discard("ren")
    def test_dequeued_messages_keep_fifo_order_without_reentering_submit(self):
        w = self.win
        scheduled = []
        dispatched = []
        w.chat_application_service._schedule = scheduled.append
        w._process_chat_request = lambda text, _attachments, _voice: dispatched.append(text)
        ren = w.sessions["ren"]
        first = w.chat_application_service.submit_message("ren", "first", force_queue=True)
        w.chat_application_service.submit_message("ren", "second", busy=True)

        w._send_next_pending(ren)
        scheduled.pop(0)()
        self.assertEqual(dispatched, ["first"])
        self.assertEqual(w.chat_application_service.pending_count("ren"), 1)
        w.chat_application_service.complete_local_request(first.request.request_id)
        w._send_next_pending(ren)
        scheduled.pop(0)()
        self.assertEqual(dispatched, ["first", "second"])
        self.assertEqual(w.chat_application_service.pending_count("ren"), 0)

    def test_removed_session_waits_for_work_then_releases_queue_worker_and_adapter(self):
        w = self.win
        scheduled = []
        w.chat_application_service._schedule = scheduled.append
        w._process_chat_request = lambda *_args: None
        ren = w.sessions["ren"]
        queued = w.chat_application_service.submit_message("ren", "queued request", force_queue=True)

        class FakeWorker:
            running = True
            deleted = False
            def isRunning(self):
                return self.running
            def deleteLater(self):
                self.deleted = True

        worker = FakeWorker()
        ren.worker = worker
        profiles = dict(w.character_service.all_profiles(w.settings))
        profiles.pop("ren", None)
        with mock.patch.object(w.character_service, "all_profiles", return_value=profiles):
            w.sync_sessions()
            self.assertIs(w.sessions["ren"], ren)
            w._send_next_pending(ren)
            scheduled.pop(0)()
            self.assertIs(w.sessions["ren"], ren)
            self.assertTrue(worker.running)
            w.chat_application_service.complete_local_request(queued.request.request_id)
            worker.running = False
            w.sync_sessions()

        self.assertNotIn("ren", w.sessions)
        self.assertEqual(w.chat_application_service.pending_count("ren"), 0)
        self.assertTrue(worker.deleted)
        self.assertIsNone(ren.worker)
        self.assertIsNone(ren.client)
        self.assertIsNone(ren.timer)
        self.assertIsNone(ren.relay)
        self.assertIsNone(ren.view)
        self.assertFalse(w.chat_application_service.has_active_request("ren"))

    def test_shutdown_clears_every_session_application_queue(self):
        w = self.win
        sessions = list(w.sessions.values())
        for session in sessions:
            w.chat_application_service.submit_message(session.cid, session.cid, force_queue=True)

        w._clear_chat_coordinator_queues()

        for session in sessions:
            self.assertEqual(w.chat_application_service.pending_count(session.cid), 0)
            self.assertFalse(w.chat_application_service.has_active_request(session.cid))
    def test_every_chat_has_its_own_router(self):
        routers = {id(s.client) for s in self.win.sessions.values()}
        self.assertEqual(len(routers), len(self.win.sessions))
        a, b = self.win.sessions["kira"].client, self.win.sessions["ren"].client
        self.assertIs(a.states, b.states)                             # health / cooldowns are shared
        self.assertIsNot(a._cancel, b._cancel)                        # Stop is not


if __name__ == "__main__":
    unittest.main()
