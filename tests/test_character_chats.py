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
        with mock.patch.object(memory, "_db", side_effect=sqlite3.OperationalError("disk I/O error")):
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
    def test_sessions_do_not_share_state(self):
        from kira.chat.coordinator import ChatCoordinator, ChatRequest
        a, b = chat_sessions.ChatSession("ren"), chat_sessions.ChatSession("mika")
        a.busy = True
        a.coordinator = ChatCoordinator(lambda _request: None)
        a.coordinator.submit(ChatRequest.create("x"), busy=True)
        self.assertFalse(b.busy)
        self.assertIsNone(b.coordinator)
        self.assertEqual(a.coordinator.pending_count, 1)

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
        from kira.main import MainWindow
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
        from kira.chat.coordinator import ChatRequest
        from kira.oldmain import ProviderResponseRelay
        w = self.win
        scheduled = []
        dispatched = []
        w._schedule_chat_callback = scheduled.append
        w._process_chat_request = lambda text, _attachments, _voice: dispatched.append(
            (w.cur.cid, text, w.front.cid)
        )
        ren, mika = w.sessions["ren"], w.sessions["mika"]
        ren.busy = mika.busy = True
        w._chat_coordinator(ren).submit(ChatRequest.create("Ren queued"), busy=True)
        w._chat_coordinator(mika).submit(ChatRequest.create("Mika queued"), busy=True)
        ren_request, mika_request = "ren-response-test", "mika-response-test"
        w.response_handler.begin_request(ren_request, "ren")
        w.response_handler.begin_request(mika_request, "mika")
        ren.response_relay = ProviderResponseRelay(w, ren, ren_request)
        mika.response_relay = ProviderResponseRelay(w, mika, mika_request)

        def completed(_result):
            session = w.cur  # ProviderResponseRelay establishes the originating session
            session.busy = False
            w._send_next_pending(session)

        w.on_stream_done = completed
        w.switch_session("kira")
        ren.response_relay.complete({"text": "Ren response"})
        w.switch_session("mika")
        mika.response_relay.complete({"text": "Mika response"})
        self.assertIsNone(ren.response_relay)
        self.assertIsNone(mika.response_relay)
        w.switch_session("kira")  # switch tabs before the queued callbacks execute

        self.assertEqual(len(scheduled), 2)
        for callback in list(scheduled):
            callback()
        self.assertEqual(
            dispatched,
            [("ren", "Ren queued", "kira"), ("mika", "Mika queued", "kira")],
        )
        self.assertEqual(w.cur.cid, "kira")

    def test_submit_queues_behind_a_request_already_reserved_for_dispatch(self):
        from kira.chat.coordinator import SubmissionResult
        w = self.win
        ren = w.sessions["ren"]
        ren.dispatch_scheduled = True
        observed = {}

        class Coordinator:
            pending_count = 1
            def submit(self, request, *, busy, force_queue):
                observed.update(request=request, busy=busy, force_queue=force_queue)
                return SubmissionResult.QUEUED

        original = w._chat_coordinator
        w._chat_coordinator = lambda _session=None: Coordinator()
        try:
            with w._as(ren):
                w.submit("message after reserved queue item")
        finally:
            w._chat_coordinator = original
            ren.dispatch_scheduled = False

        self.assertEqual(observed["request"].text, "message after reserved queue item")
        self.assertFalse(observed["busy"])
        self.assertTrue(observed["force_queue"])
    def test_dequeued_messages_keep_fifo_order_without_reentering_submit(self):
        from kira.chat.coordinator import ChatRequest
        w = self.win
        scheduled = []
        dispatched = []
        w._schedule_chat_callback = scheduled.append

        def process(text, _attachments, _voice):
            dispatched.append(text)
            w.busy = True

        w._process_chat_request = process
        ren = w.sessions["ren"]
        coordinator = w._chat_coordinator(ren)
        coordinator.submit(ChatRequest.create("first"), force_queue=True)
        coordinator.submit(ChatRequest.create("second"), busy=True)

        w._send_next_pending(ren)
        scheduled.pop(0)()
        self.assertEqual(dispatched, ["first"])
        self.assertEqual(coordinator.pending_count, 1)
        ren.busy = False  # first response completed
        w._send_next_pending(ren)
        scheduled.pop(0)()
        self.assertEqual(dispatched, ["first", "second"])
        self.assertEqual(coordinator.pending_count, 0)

    def test_removed_session_waits_for_work_then_releases_queue_worker_and_adapter(self):
        from kira.chat.coordinator import ChatRequest
        w = self.win
        scheduled = []
        w._schedule_chat_callback = scheduled.append
        w._process_chat_request = lambda *_args: None
        ren = w.sessions["ren"]
        coordinator = w._chat_coordinator(ren)
        coordinator.submit(ChatRequest.create("queued request"), force_queue=True)

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
            self.assertIs(w.sessions["ren"], ren)  # pending request and worker retain the session
            w._send_next_pending(ren)
            scheduled.pop(0)()  # dispatch the dequeued request to its owning session
            self.assertIs(w.sessions["ren"], ren)
            self.assertTrue(worker.running)
            worker.running = False
            w.sync_sessions()

        self.assertNotIn("ren", w.sessions)
        self.assertEqual(coordinator.pending_count, 0)
        self.assertTrue(worker.deleted)
        self.assertIsNone(ren.worker)
        self.assertIsNone(ren.client)
        self.assertIsNone(ren.timer)
        self.assertIsNone(ren.relay)
        self.assertIsNone(ren.view)
        self.assertIsNone(ren.coordinator)
        self.assertIsNone(ren.response_relay)
        self.assertFalse(ren.dispatch_scheduled)

    def test_shutdown_clears_every_session_coordinator_queue_and_scheduled_flag(self):
        from kira.chat.coordinator import ChatRequest
        w = self.win
        sessions = list(w.sessions.values())
        for session in sessions:
            w._chat_coordinator(session).submit(ChatRequest.create(session.cid), force_queue=True)
            session.dispatch_scheduled = True

        w._clear_chat_coordinator_queues()

        for session in sessions:
            self.assertEqual(session.coordinator.pending_count, 0)
            self.assertFalse(session.dispatch_scheduled)
    def test_every_chat_has_its_own_router(self):
        routers = {id(s.client) for s in self.win.sessions.values()}
        self.assertEqual(len(routers), len(self.win.sessions))
        a, b = self.win.sessions["kira"].client, self.win.sessions["ren"].client
        self.assertIs(a.states, b.states)                             # health / cooldowns are shared
        self.assertIsNot(a._cancel, b._cancel)                        # Stop is not


if __name__ == "__main__":
    unittest.main()
