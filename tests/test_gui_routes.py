"""Route Manager, model indicator, live streaming, Stop, queue - through the real window (Qt offscreen)."""
import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import helpers
from tests.helpers import Resp, StreamResp, sse, ndjson, CANARY

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QModelIndex, Qt
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False

import requests
from kira import config, memory
from kira import routes as route_model
from kira.hybrid_ai import HybridRouter

if HAVE_QT:
    APP = QApplication.instance() or QApplication([])


def pump(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def table(mapping):
    calls = []

    def fake(url, headers=None, json=None, timeout=None, stream=False, **kw):
        calls.append({"url": url, "json": dict(json) if isinstance(json, dict) else json})
        for key, val in mapping.items():
            if key in url:
                if isinstance(val, list):
                    val = val.pop(0)
                if callable(val) and not isinstance(val, StreamResp):
                    val = val()
                if isinstance(val, Exception):
                    raise val
                return val
        raise AssertionError("unexpected url " + url)
    fake.calls = calls
    return fake


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class RouteGuiTests(unittest.TestCase):
    def setUp(self):
        d = config.DATA_DIR / "route_gui_case"
        d.mkdir(exist_ok=True)
        self.path = d / "settings.json"
        if self.path.exists():
            self.path.unlink()
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", self.path),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot),
                        mock.patch("requests.get", side_effect=requests.ConnectionError("ollama off"))]
        for p in self.patches:
            p.start()
        memory.init_db()
        memory.clear_memory()
        from tests.window_factory import make_window
        from kira.theme import STYLE
        APP.setStyleSheet(STYLE)
        self.win = make_window()
        self.win.show()
        self.win.set_voice_enabled(False)
        APP.processEvents()

    def tearDown(self):
        w = self.win
        w.client.cancel()
        if getattr(w, "worker", None) is not None:
            w.worker.wait(3000)
        w.speaker.stop()
        w.companion.close()
        w.close()
        APP.processEvents()
        for p in self.patches:
            p.stop()

    # ---- helpers ----
    def cloud(self, *names, ollama=False):
        w = self.win
        helpers.enable(w.settings, *names)
        w.settings["providers"]["ollama"]["enabled"] = ollama
        route_model.ensure_routes(w.settings)
        w.client = HybridRouter(w.settings)
        w.set_badge("idle", w.client.preview_route())

    def send(self, text):
        self.win.input.setText(text)
        self.win.send_message()

    def done(self):
        return pump(lambda: not self.win.busy)

    def row(self, rid):
        w = self.win
        for i in range(w.route_list.count()):
            if w.route_list.item(i).data(Qt.UserRole) == rid:
                w.route_list.setCurrentRow(i)
                return
        raise AssertionError(rid)

    # ================= 2. real-time model indicator =================
    def test_indicator_before_during_after_and_error(self):
        w = self.win
        self.cloud("groq", "cloudflare")
        self.assertEqual(w.route_badge.text(), "● Ready · Groq / openai/gpt-oss-120b · Cloud")      # default route from the router
        gate, seen = threading.Event(), []
        mapping = {"groq": StreamResp(sse("سلام", done=False) + [lambda: gate.wait(5)] + sse("!"))}
        with mock.patch("requests.post", table(mapping)):
            self.send("hi")
            self.assertTrue(pump(lambda: "Connected" in w.route_badge.text()))
            seen.append(w.route_badge.text())
            self.assertIn("Groq / openai/gpt-oss-120b", seen[0])
            gate.set()
            self.assertTrue(self.done())
        self.assertTrue(w.route_badge.text().startswith("✓ Done · Groq / openai/gpt-oss-120b"))
        with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
            self.send("again")
            self.assertTrue(self.done())
        self.assertEqual(w.route_badge.text(), "✕ Error")

    def test_indicator_shows_failover_route_and_final_model(self):
        w = self.win
        self.cloud("groq", "cloudflare")
        gate, texts = threading.Event(), []
        mapping = {"groq": Resp(500), "cloudflare": StreamResp([lambda: gate.wait(5)] + sse({"response": "ok"}))}
        with mock.patch("requests.post", table(mapping)):
            self.send("hi")
            self.assertTrue(pump(lambda: "Cloudflare" in w.route_badge.text()))
            texts.append(w.route_badge.text())
            gate.set()
            self.assertTrue(self.done())
        self.assertTrue(texts[0].startswith(("↪ Failover", "◌ Processing", "● Connected")), texts)
        self.assertIn("Cloudflare Workers AI / @cf/meta/llama-3.1-8b-instruct", w.route_badge.text())
        self.assertIn("Failover×1", w.status.text())

    def test_indicator_names_come_from_router_not_settings(self):
        w = self.win
        self.cloud("groq")
        w.settings["providers"]["groq"]["model"] = "stale-name-in-provider-block"      # old-style field must not leak into the badge
        w.set_badge("idle", w.client.preview_route())
        self.assertIn("openai/gpt-oss-120b", w.route_badge.text())
        self.assertNotIn("stale-name", w.route_badge.text())

    def test_badge_menu_lists_routes_manual_choice_wins_and_persists(self):
        w = self.win
        self.cloud("groq", "cloudflare", "mistral")
        w.build_badge_menu()
        labels = [a.text() for a in w.route_menu.actions() if a.text()]
        self.assertTrue(labels[0].startswith("جزئیات"))
        self.assertTrue(any("Mistral" in x for x in labels))
        mist = next(a for a in w.route_menu.actions() if "Mistral" in a.text())
        mist.trigger()
        self.assertEqual(w.settings["manual_route_id"], "mistral")
        self.assertIn("Mistral / mistral-small-latest", w.route_badge.text())
        f = table({"mistral": StreamResp(sse("m")), "groq": AssertionError("manual choice must win")})
        with mock.patch("requests.post", f):
            self.send("hi")
            self.assertTrue(self.done())
        self.assertIn("mistral", f.calls[0]["url"])
        self.assertEqual(config.load_settings()["manual_route_id"], "mistral")                    # autosaved, no Save click
        w.build_badge_menu()
        next(a for a in w.route_menu.actions() if a.text().startswith("خودکار")).trigger()
        self.assertEqual(w.settings["manual_route_id"], "")

    def test_badge_details_dialog(self):
        w = self.win
        self.cloud("groq")
        with mock.patch("PySide6.QtWidgets.QMessageBox.information") as box:
            w.show_route_details()
        text = box.call_args[0][2]
        for part in ("Groq", "openai/gpt-oss-120b", "Cloud", "Timeout"):
            self.assertIn(part, text)

    # ================= 4. real streaming =================
    def test_text_appears_progressively_before_the_answer_ends(self):
        w = self.win
        self.cloud("groq")
        gate = threading.Event()
        lines = sse("[happy]\n", "سلام " + "الف" * 45, done=False) + [lambda: gate.wait(5)] + sse("دنیای زیبا", done=True)
        with mock.patch("requests.post", table({"groq": StreamResp(lines)})):
            self.send("hello")
            self.assertTrue(pump(lambda: "سلام" in w.chat.toPlainText().split("hello")[-1]))
            mid = w.chat.toPlainText()
            self.assertTrue(w.busy)                                         # still generating
            self.assertTrue(w.gen_stop_btn.isVisibleTo(w))
            self.assertNotIn("دنیای زیبا", mid)
            self.assertNotIn("[happy]", mid)                                # mood tag never shown
            self.assertTrue(w.input.isEnabled())                            # typing is never blocked
            gate.set()
            self.assertTrue(self.done())
        final = w.chat.toPlainText()
        self.assertEqual(final.count("سلام " + "الف" * 45 + "دنیای زیبا"), 1)                  # one bubble, no duplicated text
        self.assertEqual(final.count("hello"), 1)
        self.assertFalse(w.gen_stop_btn.isVisibleTo(w))
        self.assertEqual(memory.recent_messages(5)[-1]["content"], "[happy]\nسلام " + "الف" * 45 + "دنیای زیبا")

    def test_ui_stays_responsive_during_a_slow_stream(self):
        w = self.win
        self.cloud("groq")
        gate, ticks = threading.Event(), []
        from PySide6.QtCore import QTimer
        t = QTimer()
        t.timeout.connect(lambda: ticks.append(1))
        t.start(10)
        with mock.patch("requests.post", table({"groq": StreamResp(sse("a", done=False) + [lambda: gate.wait(0.6)] + sse("b"))})):
            self.send("x")
            self.assertTrue(self.done())
        t.stop()
        self.assertGreaterEqual(len(ticks), 15)                              # the event loop kept running while the worker waited

    def test_stop_button_keeps_partial_text_saves_it_and_allows_next_message(self):
        w = self.win
        self.cloud("groq")
        gate = threading.Event()
        mapping = {"groq": [StreamResp(sse("نیمه‌ی اول " + "الف" * 45, done=False) + [lambda: gate.wait(5)] + sse("نباید دیده شود")), StreamResp(sse("پاسخ بعدی"))]}
        with mock.patch("requests.post", table(mapping)):
            self.send("first")
            self.assertTrue(pump(lambda: ("نیمه‌ی اول " + "الف" * 45) in w.chat.toPlainText()))
            w.gen_stop_btn.click()
            gate.set()
            self.assertTrue(self.done())
            text = w.chat.toPlainText()
            self.assertIn("نیمه‌ی اول " + "الف" * 45, text)
            self.assertNotIn("نباید دیده شود", text)
            self.assertIn("متوقف شد", text)
            self.assertEqual(w.route_badge.text()[:9], "■ Stopped")
            self.assertEqual(memory.recent_messages(5)[-1]["content"], "نیمه‌ی اول " + "الف" * 45)
            self.send("second")
            self.assertTrue(self.done())
        self.assertIn("پاسخ بعدی", w.chat.toPlainText())
        self.assertNotIn("groq", w.client.cooldowns)

    def test_connection_lost_mid_answer_keeps_partial_once_and_does_not_restart_elsewhere(self):
        w = self.win
        self.cloud("groq", "cloudflare")
        groq = StreamResp(sse("بخش اول " + "الف" * 45, done=False) + [requests.ConnectionError("reset")])
        f = table({"groq": groq, "cloudflare": AssertionError("must not repeat the answer on another route")})
        with mock.patch("requests.post", f):
            self.send("hi")
            self.assertTrue(self.done())
        text = w.chat.toPlainText()
        self.assertEqual(text.count("بخش اول " + "الف" * 45), 1)
        self.assertIn("قطع شد", text)
        self.assertEqual(len(f.calls), 1)
        self.assertTrue(w.send_btn.isEnabled())

    def test_message_typed_during_generation_is_queued_then_sent_in_order(self):
        w = self.win
        self.cloud("groq")
        gate = threading.Event()
        mapping = {"groq": [StreamResp([lambda: gate.wait(5)] + sse("one")), StreamResp(sse("two"))]}
        f = table(mapping)
        with mock.patch("requests.post", f):
            self.send("q1")
            self.assertTrue(pump(lambda: w.busy and w.worker.isRunning()))
            self.send("q2")
            self.assertEqual(w._pending, [("q2", [], False)])   # (text, attachments, voice)
            self.assertNotIn("q2", w.chat.toPlainText())                      # not shown until it is really sent
            gate.set()
            self.assertTrue(pump(lambda: "two" in w.chat.toPlainText() and not w.busy and not w._pending))
        text = w.chat.toPlainText()
        self.assertLess(text.index("one"), text.index("q2"))
        self.assertLess(text.index("q2"), text.index("two"))
        self.assertEqual(len(f.calls), 2)

    def test_streamed_persian_bubble_is_rtl_and_tag_only_reply_retries_once(self):
        w = self.win
        self.cloud("groq")
        mapping = {"groq": [StreamResp(sse("[happy]")), StreamResp(sse("سلام کیرا هستم"))]}
        f = table(mapping)
        with mock.patch("requests.post", f):
            self.send("hi")
            self.assertTrue(self.done())
        self.assertEqual(len(f.calls), 2)
        self.assertNotIn("[happy]", f.calls[1]["json"]["messages"][0]["content"])      # second try asked without tags
        block = None
        b = w.chat.document().begin()
        while b.isValid():
            if "سلام کیرا هستم" in b.text():
                block = b
            b = b.next()
        self.assertIsNotNone(block)
        self.assertEqual(block.blockFormat().layoutDirection(), Qt.RightToLeft)

    def test_ollama_route_streams_in_the_window(self):
        w = self.win
        helpers.enable(w.settings)                                       # no cloud
        w.settings["providers"]["ollama"]["enabled"] = True
        w.client = HybridRouter(w.settings)
        with mock.patch("requests.post", table({"11434": StreamResp(ndjson("[sad]\n", "غمگین ", "هستم"))})):
            self.send("hi")
            self.assertTrue(self.done())
        self.assertIn("غمگین هستم", w.chat.toPlainText())
        self.assertIn("Ollama / qwen3.5:4b", w.route_badge.text())
        self.assertIn("Local", w.route_badge.text())
        pump(lambda: w.animator.expr == "sad", 2.0)                        # the emotion animator syncs the face on its next frame
        self.assertEqual(w.animator.expr, "sad")

    # ================= 1. Route Manager =================
    def test_add_provider_add_models_edit_disable_delete_autosave(self):
        w = self.win
        pid = w.add_provider_from_values("LM Studio", "http://localhost:1234/v1", "", True, "qwen-7b")
        self.assertIn(pid, [w.api_table.item(i, 0).data(Qt.UserRole) for i in range(w.api_table.rowCount())])
        self.assertIn("LM Studio / qwen-7b", "\n".join(w.route_list.item(i).text() for i in range(w.route_list.count())))
        r2 = w.add_route_from_values(pid, "llama-8b")
        self.assertEqual(sum(r["provider"] == pid for r in route_model.get_routes(w.settings)), 2)        # many models, one provider
        self.assertIsNone(w.add_route_from_values(pid, "llama-8b"))                                          # duplicate refused
        self.assertIn("✕", w.route_status.text())
        self.row(r2["id"])
        w.route_timeout.setValue(120)                                                                         # edits autosave
        w.route_enabled_chk.setChecked(False)
        saved = config.load_settings()
        r = route_model.find_route(saved, r2["id"])
        self.assertEqual((r["timeout"], r["enabled"]), (120, False))
        self.assertEqual(saved["providers"][pid]["base_url"], "http://localhost:1234/v1")
        with mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.Yes):
            w.delete_selected_route()
            self.assertFalse(route_model.find_route(config.load_settings(), r2["id"]))
            w.remove_provider_ui(pid)
        self.assertNotIn(pid, config.load_settings()["providers"])
        self.assertNotIn(pid, [w.api_table.item(i, 0).data(Qt.UserRole) for i in range(w.api_table.rowCount())])

    def test_api_enable_disable_autosaves_encrypted_and_keeps_key(self):
        w = self.win
        w.settings["providers"]["mistral"].update({"enabled": True, "api_key": f"{CANARY}-mistral"})
        w.api_toggle("mistral")                                             # -> disabled, saved
        self.assertNotIn(CANARY, self.path.read_text(encoding="utf-8"))
        saved = config.load_settings()["providers"]["mistral"]
        self.assertEqual((saved["api_key"], saved["enabled"]), (f"{CANARY}-mistral", False))
        w.api_toggle("mistral")
        self.assertTrue(config.load_settings()["providers"]["mistral"]["enabled"])

    def test_drag_and_drop_reorder_sets_priority_and_survives_restart(self):
        w = self.win
        ids = lambda: [w.route_list.item(i).data(Qt.UserRole) for i in range(w.route_list.count())]          # noqa: E731
        w.route_list.model().moveRow(QModelIndex(), ids().index("mistral"), QModelIndex(), 0)
        APP.processEvents()
        APP.processEvents()
        self.assertEqual([r["id"] for r in route_model.get_routes(w.settings)][0], "mistral")
        self.assertEqual(config.load_settings()["provider_order"][0], "mistral")
        from tests.window_factory import make_window
        w2 = make_window()
        self.assertEqual(w2.route_list.item(0).data(Qt.UserRole), "mistral")
        self.assertTrue(w2.route_list.item(0).text().startswith("1."))
        w2.companion.close()
        w2.close()

    def test_failover_toggle(self):
        # Reordering is drag-and-drop only (up/down/default buttons were removed); move/default logic lives in routes.py.
        w = self.win
        self.row("openrouter")
        w.failover_chk.setChecked(False)
        self.assertFalse(config.load_settings()["failover_enabled"])
        for removed in ("route_up_btn", "route_down_btn", "route_default_btn", "route_bench_all_btn"):
            self.assertFalse(hasattr(w.presentation_context.views, removed) and getattr(w.presentation_context.views, removed, None) is not None)

    def test_ollama_scan_adds_installed_models_disabled(self):
        w = self.win

        def fake_get(url, timeout=None, **kw):
            return Resp(200, {"models": [{"name": "qwen3.5:4b"}, {"name": "llama3.2:3b"}]})
        with mock.patch("requests.get", fake_get):
            w.scan_ollama()
            self.assertTrue(pump(lambda: w.route_scan_btn.isEnabled() and "✓" in w.route_status.text()))
        added = [r for r in route_model.get_routes(w.settings) if r["model"] == "llama3.2:3b"]
        self.assertEqual(len(added), 1)
        self.assertFalse(added[0]["enabled"])
        self.assertIn("llama3.2:3b", [w.model.itemText(i) for i in range(w.model.count())])
        with mock.patch("requests.get", side_effect=requests.ConnectionError("off")):
            w.scan_ollama()
            self.assertTrue(pump(lambda: w.route_scan_btn.isEnabled() and "✕" in w.route_status.text()))
        self.assertIn("Ollama", w.route_status.text())

    def test_route_test_button_updates_health_in_list(self):
        w = self.win
        self.cloud("groq")
        self.row("groq")
        get = mock.Mock(return_value=Resp(200, {"data": [{"id": "openai/gpt-oss-120b"}]}))
        with mock.patch("requests.get", get), mock.patch("requests.post", table({"groq": Resp(200, {"choices": [{"message": {"content": "OK"}}]})})):
            w.test_selected_route()
            self.assertTrue(pump(lambda: w.route_test_btn.isEnabled() and "✓" in w.route_status.text()))
        self.assertIn("● سالم", w.route_list.currentItem().text())
        with mock.patch("requests.get", mock.Mock(return_value=Resp(401, {"error": {"message": f"bad {CANARY}-groq"}}))):
            w.test_selected_route()
            self.assertTrue(pump(lambda: w.route_test_btn.isEnabled() and "✕" in w.route_status.text()))
        self.assertNotIn(CANARY, w.route_status.text())
        self.assertIn("✕ خراب", w.route_list.currentItem().text())

    def test_benchmark_button_runs_selected_routes_sequentially_after_confirmation(self):
        w = self.win
        self.cloud("groq", ollama=True)
        QMB = __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox
        f = table({"groq": lambda: StreamResp(sse("x" * 30)), "11434": lambda: StreamResp(ndjson("hello"))})
        with mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMB.Yes) as q, mock.patch("requests.post", f):
            w.run_benchmark(True)
            self.assertTrue(w.busy)
            self.assertTrue(pump(lambda: not w.busy))
        q.assert_called_once()                                                  # cost warning shown for the cloud route
        out = w.bench_out.toPlainText()
        self.assertIn("Groq / openai/gpt-oss-120b", out)
        self.assertIn("Ollama / qwen3.5:4b", out)
        self.assertIn("tok/s", out)
        self.assertIn("سریع‌ترین اولین Token", out)
        self.assertEqual(len(f.calls), 2)
        with mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMB.No), mock.patch("requests.post", side_effect=AssertionError("declined")):
            w.run_benchmark(True)
        self.assertFalse(w.busy)

    # ================= 3 / 5.4 stability =================
    def test_many_sequential_conversations_with_route_changes_stay_healthy(self):
        w = self.win
        self.cloud("groq", "cloudflare")
        n = 0

        def maker(url, **kw):
            nonlocal n
            n += 1
            if "groq" in url:
                return StreamResp(sse(f"پاسخ {n}"))
            return StreamResp(sse({"response": f"پاسخ {n}"}))
        with mock.patch("requests.post", maker):
            for i in range(25):
                if i % 5 == 0:
                    w.select_route("cloudflare" if (i // 5) % 2 == 0 else "")            # switch route during use
                self.send(f"سوال {i}")
                self.assertTrue(self.done(), i)
                if i == 0:
                    import weakref
                    first_worker = weakref.ref(w.worker)
        self.assertFalse(w.busy)
        self.assertTrue(w.send_btn.isEnabled() and w.input.isEnabled())
        self.assertLessEqual(len(w.client.metrics), 200)
        self.assertEqual(w.chat.toPlainText().count("پاسخ "), 25)
        self.assertFalse(w.worker.isRunning())
        self.assertEqual(len(memory.recent_messages(100)), 50)
        import gc
        gc.collect()
        self.assertIsNone(first_worker())                                                    # a finished worker is released, not kept forever

    def test_telemetry_files_never_contain_chat_text_or_keys(self):
        import os
        w = self.win
        self.cloud("groq")
        with mock.patch("requests.post", table({"groq": StreamResp(sse("متن خصوصی پاسخ"))})):
            self.send("پرسش خصوصی")
            self.assertTrue(self.done())
        log = os.path.join(os.environ["KIRA_LOG_DIR"], "provider_telemetry.jsonl")
        data = open(log, encoding="utf-8").read()
        for bad in ("متن خصوصی", "پرسش خصوصی", CANARY):
            self.assertNotIn(bad, data)
        self.assertIn("first_token_ms", data)

    def test_close_while_generating_does_not_hang_or_crash(self):
        w = self.win
        self.cloud("groq")
        gate = threading.Event()
        with mock.patch("requests.post", table({"groq": StreamResp(sse("a" * 48, done=False) + [lambda: gate.wait(1.5)] + sse("b"))})):
            self.send("x")
            self.assertTrue(pump(lambda: "a" * 48 in w.chat.toPlainText()))
            t0 = time.time()
            w.close()
            self.assertLess(time.time() - t0, 6)
        self.assertFalse(w.worker.isRunning())


if __name__ == "__main__":
    unittest.main()
