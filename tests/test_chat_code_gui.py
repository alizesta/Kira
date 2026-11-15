"""Ai1 Code inside Kira's chat (Qt offscreen). Proves wiring and safety gates; the real Windows desktop still needs a manual try."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import helpers

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QUrl
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False

import requests
from kira import about, config, memory
from kira.code_agent import PATCH_START, PATCH_END

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


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ChatCodeGuiTests(unittest.TestCase):
    def setUp(self):
        d = config.DATA_DIR / "gui_case_code"
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
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name)
        (self.proj / "app.py").write_text("def save():\n    return 1\n", encoding="utf-8")
        from kira.main import MainWindow, STYLE
        APP.setStyleSheet(STYLE)
        self.win = MainWindow()
        self.win.show()
        APP.processEvents()
        self.cc = self.win.code_chat
        self.cc.pick_folder = lambda: str(self.proj)
        self.cc.confirm = lambda *a, **k: True

    def tearDown(self):
        self.win.speaker.stop()
        self.win.companion.close()
        self.win.close()
        APP.processEvents()
        self.tmp.cleanup()
        for p in self.patches:
            p.stop()

    # helpers
    def fake_model(self, text):
        self.win.sessions["kira"].client.chat_stream = lambda messages, system, temperature=0.7, on_chunk=None, **kw: (
            on_chunk(text) if on_chunk else None, {"text": text})[1]

    def script_model(self, *replies, plan="1. inspect\n2. fix\n3. test", review="CLEAN"):
        from kira import auto_agent as aa
        queue = list(replies)

        def chat_stream(messages, system, temperature=0.7, on_chunk=None, **kw):
            if system == aa.PLAN_PROMPT or "senior software architect" in str(system).lower():
                return {"text": plan}
            if "independent code reviewer" in str(system).lower():
                return {"text": review}
            r = queue.pop(0)
            return {"text": r if isinstance(r, str) else json.dumps(r)}
        self.win.sessions["kira"].client.chat_stream = chat_stream

    def send(self, text):
        w = self.win
        w.input.setText(text)
        w.send_message()
        self.assertTrue(pump(lambda: not w.busy), "the turn never finished")
        APP.processEvents()

    def send_when_idle(self, text):
        """For wording the model has to classify first: wait for the whole chain (decision, agent, answer)."""
        w = self.win
        w.input.setText(text)
        w.send_message()
        end = time.time() + 20
        while time.time() < end and (self.cc._classifying or w.busy or self.cc.job is not None):
            QCoreApplication.processEvents()
            time.sleep(0.01)
        APP.processEvents()

    def chat_text(self):
        return self.win.chat.toPlainText()

    def turn_on(self):
        """Give Kira a project folder (the way the first coding request would)."""
        self.assertTrue(self.cc.choose_project())
        self.assertEqual(self.cc.root, self.proj.resolve())

    # ---- mandatory version metadata (PROJECT_CONTEXT.md)
    def test_about_shows_version_build_date_time_and_developer(self):
        labels = self.win.about_labels
        self.assertEqual(list(labels), list(about.ROW_KEYS))
        expected = dict(about.about_rows(config.VERSION))
        for key in about.ROW_KEYS:
            self.assertEqual(labels[key].text(), expected[key], key)
        self.assertEqual(labels["about_version"].text(), config.VERSION)
        self.assertRegex(labels["about_build_date"].text(), r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(labels["about_build_time"].text(), r"^([01]\d|2[0-3]):[0-5]\d$")
        self.assertIn(labels["about_developer"].text(), ("Codex", "OpenCode", "Claude Code", "ChatGPT"))

    # ---- no button, Kira understands
    def test_no_button_and_not_in_menu(self):
        from PySide6.QtWidgets import QAbstractButton
        w = self.win
        self.assertNotIn("Ai1 Code", [a.text() for a in w.nav_menu.actions()])
        self.assertFalse(hasattr(self.cc, "button"))
        self.assertFalse([b for b in w.findChildren(QAbstractButton) if b.text().strip() == "</>"])

    def test_first_coding_request_asks_for_the_project_folder_once(self):
        asked = []
        self.cc.pick_folder = lambda: (asked.append(1), str(self.proj))[1]
        self.cc.auto_dir = self.proj.parent / (self.proj.name + "_out")
        self.cc.auto_python = sys.executable
        self.script_model({"action": "finish", "summary": "نگاه کردم"})
        self.send("ببین پروژه رو بررسی کن و بگو مشکلی هست؟")
        self.assertEqual(len(asked), 1)
        self.assertEqual(Path(self.win.settings["code_workspace_path"]).resolve(), self.proj.resolve())
        self.script_model({"action": "finish", "summary": "باز هم نگاه کردم"})
        self.send("اون فایل app.py رو دوباره بررسی کن")
        self.assertEqual(len(asked), 1)                       # remembered: never asked again

    def test_cancelling_the_folder_dialog_starts_nothing(self):
        self.cc.pick_folder = lambda: ""
        self.script_model("SHOULD NOT BE USED")
        self.send("پروژه رو بررسی کن و درست کن")
        self.assertIsNone(self.cc.root)
        self.assertIn("بدون پوشه", self.chat_text())

    def test_normal_talk_is_left_to_the_normal_chat(self):
        self.turn_on()
        for text in ("سلام کیرا خوبی؟", "مرسی", "تفاوت list و tuple چیه؟"):
            self.assertFalse(self.cc.handle(text), text)

    def test_other_tabs_are_not_intercepted(self):
        self.turn_on()
        self.win.switch_session("ren")
        APP.processEvents()
        self.assertFalse(self.cc.handle("فایل app.py رو درست کن"))

    # ---- ambiguous wording: the model decides
    def spy_submit(self):
        calls, original = [], self.win.submit
        self.win.submit = lambda text, attachments=None: calls.append(text) if self.cc._bypass else original(text, attachments)
        return calls

    def test_ambiguous_message_judged_chat_goes_to_the_normal_chat(self):
        self.turn_on()
        calls = self.spy_submit()
        self.script_model("CHAT")
        self.win.input.setText("این تابع رو درست کن")
        self.win.send_message()
        self.assertTrue(pump(lambda: calls), "never reached the normal chat")
        self.assertEqual(calls, ["این تابع رو درست کن"])
        self.assertFalse(self.cc._classifying)

    def test_ambiguous_message_judged_task_starts_the_agent(self):
        self.turn_on()
        self.cc.auto_dir = self.proj.parent / (self.proj.name + "_out")
        self.cc.auto_python = sys.executable
        self.script_model("TASK", {"action": "write", "path": "x.txt", "content": "1"}, {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                          {"action": "review"}, {"action": "finish", "summary": "ساخته شد"})
        self.win.input.setText("این تابع رو درست کن")
        self.win.send_message()
        self.assertTrue(pump(lambda: list(self.cc.auto_dir.glob("*.zip")), 20), "the agent never delivered")
        self.assertTrue(pump(lambda: not self.win.busy))
        self.assertIn("این تابع رو درست کن", self.chat_text())

    def test_failed_classifier_falls_back_to_the_normal_chat(self):
        self.turn_on()
        calls = self.spy_submit()
        def boom(*a, **k):
            raise RuntimeError("offline")
        self.win.sessions["kira"].client.chat_stream = boom
        self.win.input.setText("این تابع رو درست کن")
        self.win.send_message()
        self.assertTrue(pump(lambda: calls))

    def test_classifier_error_on_a_deleted_or_invalid_project_path_does_not_get_stuck(self):
        self.turn_on()
        for bad in (self.proj / "deleted_project", self.proj / "app.py"):
            calls = self.spy_submit()
            self.cc.root = bad                                  # deleted folder / a file instead of a folder
            self.win.input.setText("این تابع رو درست کن")
            self.win.send_message()
            self.assertTrue(pump(lambda: calls), f"the message was dropped for {bad}")
            self.assertEqual(calls, ["این تابع رو درست کن"], bad)
            self.assertFalse(self.cc._classifying, bad)

    def test_classification_result_stays_in_kira_when_another_tab_is_in_front(self):
        self.turn_on()
        started, release = threading.Event(), threading.Event()

        def slow_model(messages, system, temperature=0.7, on_chunk=None, **kw):
            started.set()
            release.wait(5)
            return {"text": "QUESTION"}

        self.win.sessions["kira"].client.chat_stream = slow_model
        kira, ren = self.win.sessions["kira"], self.win.sessions["ren"]
        kira_before, ren_before = kira.view.toPlainText(), ren.view.toPlainText()
        with mock.patch.object(self.cc, "start_auto") as started_auto:
            self.win.input.setText("این تابع رو درست کن")
            self.win.send_message()
            self.assertTrue(started.wait(5), "the classifier never ran")
            self.win.switch_session("ren")
            APP.processEvents()
            release.set()
            self.assertTrue(pump(lambda: not self.cc._classifying, 10), "the decision never finished")
        self.assertEqual(self.win.cur.cid, "ren")              # the visible tab never moved
        self.assertIn("این تابع رو درست کن", kira.view.toPlainText())
        self.assertNotEqual(kira.view.toPlainText(), kira_before)
        self.assertEqual(ren.view.toPlainText(), ren_before)   # Ren's conversation untouched
        kira_saved = [m["content"] for m in memory.recent_messages(20, "kira")]
        ren_saved = [m["content"] for m in memory.recent_messages(20, "ren")]
        self.assertIn("این تابع رو درست کن", kira_saved)
        self.assertNotIn("این تابع رو درست کن", ren_saved)
        started_auto.assert_called_once()
        self.assertFalse(kira.busy)
        self.assertFalse(ren.busy)

    def test_chat_decision_is_submitted_to_kira_not_to_the_visible_tab(self):
        self.turn_on()
        started, release = threading.Event(), threading.Event()

        def slow_model(messages, system, temperature=0.7, on_chunk=None, **kw):
            started.set()
            release.wait(5)
            return {"text": "CHAT"}

        self.win.sessions["kira"].client.chat_stream = slow_model
        original_submit, seen = self.win.submit, []

        def submit_spy(text, attachments=None):
            if self.cc._bypass:
                seen.append((text, self.win.cur.cid))
            else:
                original_submit(text, attachments)

        self.win.submit = submit_spy
        self.win.input.setText("این تابع رو درست کن")
        self.win.send_message()
        self.assertTrue(started.wait(5), "the classifier never ran")
        self.win.switch_session("ren")
        APP.processEvents()
        release.set()
        self.assertTrue(pump(lambda: seen, 10), "the message never reached the normal chat")
        self.assertEqual(seen, [("این تابع رو درست کن", "kira")])
        self.assertEqual(self.win.cur.cid, "ren")
        self.assertFalse(self.cc._classifying)

    # ---- ask
    def test_question_is_answered_in_chat_and_saved(self):
        self.turn_on()
        self.fake_model("مشکل از ```return 1``` است.\n```python\nreturn 2\n```")
        self.send("/ask @app.py این تابع چه می‌کند؟")
        text = self.chat_text()
        self.assertIn("مشکل از", text)
        self.assertIn("return 2", text)
        self.assertIsNone(self.win.worker)                    # the normal StreamWorker never ran
        saved = [m["content"] for m in memory.recent_messages(10, "kira")]
        self.assertTrue(any("مشکل از" in c for c in saved))
        self.assertEqual(self.cc.current_rel, "app.py")

    # ---- patch -> diff -> approve / reject
    def propose(self, new_code="def save():\n    return 2\n"):
        self.fake_model(f"{PATCH_START}\n{new_code}{PATCH_END}")
        self.send("/patch @app.py مقدار برگشتی را ۲ کن، درستش کن")

    def test_patch_shows_a_diff_and_changes_nothing_until_approved(self):
        self.turn_on()
        self.propose()
        html = self.win.chat.toHtml()
        self.assertIn("kira-code://apply/", html)
        self.assertIn("kira-code://reject/", html)
        self.assertIn("return 2", self.chat_text())
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 1\n")
        self.assertEqual(len(self.cc.patches), 1)

    def test_approve_link_applies_with_backup(self):
        self.turn_on()
        self.propose()
        pid = self.cc.patches.last().pid
        self.win.on_chat_link(QUrl(f"kira-code://apply/{pid}"))
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 2\n")
        self.assertEqual((self.proj / "app.py.ai1code.bak").read_text(encoding="utf-8"), "def save():\n    return 1\n")
        self.assertEqual(len(self.cc.patches), 0)
        self.assertIn("اعمال شد", self.chat_text())

    def test_declining_the_confirmation_leaves_the_file_and_the_proposal(self):
        self.turn_on()
        self.propose()
        self.cc.confirm = lambda *a, **k: False
        self.win.on_chat_link(QUrl(f"kira-code://apply/{self.cc.patches.last().pid}"))
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 1\n")
        self.assertEqual(len(self.cc.patches), 1)

    def test_reject_link_discards_the_proposal(self):
        self.turn_on()
        self.propose()
        self.win.on_chat_link(QUrl(f"kira-code://reject/{self.cc.patches.last().pid}"))
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 1\n")
        self.assertEqual(len(self.cc.patches), 0)

    def test_stale_proposal_is_not_applied(self):
        self.turn_on()
        self.propose()
        (self.proj / "app.py").write_text("def save():\n    return 99\n", encoding="utf-8")   # edited elsewhere meanwhile
        self.win.on_chat_link(QUrl(f"kira-code://apply/{self.cc.patches.last().pid}"))
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 99\n")
        self.assertIn("تغییر کرده", self.chat_text())

    def test_text_commands_apply_and_reject_the_last_proposal(self):
        self.turn_on()
        self.propose()
        self.win.input.setText("/apply")
        self.win.send_message()
        APP.processEvents()
        self.assertIn("return 2", (self.proj / "app.py").read_text(encoding="utf-8"))

    def test_patch_without_a_file_asks_for_one_and_never_calls_the_model(self):
        self.turn_on()
        self.fake_model("SHOULD NOT BE USED")
        self.send("/patch تابع را درست کن")
        self.assertIn("فایل را مشخص کنی", self.chat_text())
        self.assertNotIn("SHOULD NOT BE USED", self.chat_text())

    def test_secret_file_is_never_sent_or_patched(self):
        (self.proj / ".env").write_text("TOKEN=abc", encoding="utf-8")
        self.turn_on()
        self.fake_model("x")
        self.send("/patch @.env درستش کن")
        self.assertEqual((self.proj / ".env").read_text(encoding="utf-8"), "TOKEN=abc")
        self.assertEqual(len(self.cc.patches), 0)

    def test_unchanged_proposal_says_so(self):
        self.turn_on()
        self.propose(new_code="def save():\n    return 1\n")
        self.assertIn("تغییری پیشنهاد نکرد", self.chat_text())
        self.assertEqual(len(self.cc.patches), 0)

    def test_model_failure_is_reported_and_chat_is_free_again(self):
        self.turn_on()
        def boom(*a, **k):
            raise RuntimeError("no route")
        self.win.sessions["kira"].client.chat_stream = boom
        self.send("/ask @app.py توضیح بده")
        self.assertIn("no route", self.chat_text())
        self.assertFalse(self.win.busy)

    # ---- autonomous agent (plain words, no @file, no command)
    def prepare_auto(self):
        self.turn_on()
        self.cc.auto_dir = self.proj.parent / (self.proj.name + "_out")
        self.cc.auto_python = sys.executable

    def test_a_plain_task_runs_the_agent_and_delivers_a_zip(self):
        (self.proj / "test_app.py").write_text(
            "import unittest\nfrom app import save\n\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(save(), 2)\n", encoding="utf-8")
        self.prepare_auto()
        self.script_model(
            {"action": "list"},
            {"action": "search", "pattern": "def save"},
            {"action": "read", "path": "app.py"},          # source must be read before planning
            {"action": "plan", "steps": ["find save", "fix", "test"]},
            {"action": "replace", "path": "app.py", "old": "return 1", "new": "return 2"},
            {"action": "run", "args": ["python", "-m", "unittest", "-v"]},
            {"action": "review"},
            {"action": "finish", "summary": "save() fixed"})
        self.send("باگ تابع save را پیدا کن و درست کن، تست‌ها را هم بزن")
        text = self.chat_text()
        self.assertIn("برنامه", text)
        self.assertIn("exit 0", text)
        self.assertIn("کار خودکار تمام شد", text)
        self.assertIn("save() fixed", text)
        zips = list(self.cc.auto_dir.glob("*_IRST.zip"))
        self.assertEqual(len(zips), 1)
        self.assertRegex(zips[0].name, r"^[\w.\-]+_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_IRST\.zip$")
        import zipfile
        self.assertIn("return 2", zipfile.ZipFile(zips[0]).read("app.py").decode())
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 1\n")   # original untouched
        self.assertIn("kira-code://open/1", self.win.chat.toHtml())
        self.assertFalse(self.win.busy)
        with mock.patch("kira.chat_code_ui.QDesktopServices.openUrl") as opened:
            self.win.on_chat_link(QUrl("kira-code://open/1"))
            opened.assert_called_once()
            self.win.on_chat_link(QUrl("kira-code://open/99"))
            opened.assert_called_once()

    def test_auto_result_ids_are_monotonic_and_unique(self):
        first = self.cc._store_auto_result(Path("one.zip"))
        second = self.cc._store_auto_result(Path("two.zip"))
        self.assertEqual((first, second), ("1", "2"))
        self.assertEqual(set(self.cc.auto_results), {"1", "2"})
        self.assertEqual(self.cc.auto_results["2"], Path("two.zip"))

    def test_shutdown_stops_running_jobs_and_clears_them(self):
        job = mock.Mock()
        job.isRunning.return_value = True
        job.wait.return_value = True
        class_job = mock.Mock()
        class_job.isRunning.return_value = True
        class_job.wait.return_value = True
        self.cc.job, self.cc._class_job = job, class_job
        self.cc.shutdown()
        self.assertTrue(self.cc.auto_stop)
        self.assertIsNone(self.cc.job)
        self.assertIsNone(self.cc._class_job)
        job.requestInterruption.assert_called_once()
        job.deleteLater.assert_called_once()
        class_job.requestInterruption.assert_called_once()

    def test_declining_the_start_confirmation_runs_nothing(self):
        self.prepare_auto()
        self.cc.confirm = lambda *a, **k: False
        self.script_model("SHOULD NOT BE USED")
        self.send("پروژه را چک کن و درست کن")
        self.assertIn("لغو شد", self.chat_text())
        self.assertFalse(list(self.cc.auto_dir.glob("*.zip")))

    def test_a_plain_question_is_investigated_read_only_without_a_file_name(self):
        self.prepare_auto()
        self.script_model("QUESTION", {"action": "search", "pattern": "def save"},
                          {"action": "finish", "summary": "تابع save در app.py خط ۱ است."})
        self.send_when_idle("تابع save کجاست؟")
        self.assertIn("app.py خط ۱", self.chat_text())
        self.assertFalse(list(self.cc.auto_dir.glob("*.zip")))
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "def save():\n    return 1\n")

    def test_terminal_command_asks_the_person_and_logs_output_in_chat(self):
        self.prepare_auto()
        self.cc.auto_shell = (sys.executable, ["-c"])
        answers = iter([True, True])                                   # start dialog, then the shell approval
        asked = []
        self.cc.confirm = lambda title, text, **k: (asked.append(text), next(answers))[1]
        self.script_model({"action": "shell", "command": "print('from-agent-shell')"}, {"action": "finish", "summary": "ok"})
        self.send("پروژه را چک کن و درست کن")
        self.assertIn("from-agent-shell", self.chat_text())
        self.assertTrue(any("print('from-agent-shell')" in t for t in asked))

    def test_denied_terminal_command_is_not_run(self):
        self.prepare_auto()
        self.cc.auto_shell = (sys.executable, ["-c"])
        answers = iter([True, False])
        self.cc.confirm = lambda *a, **k: next(answers)
        self.script_model({"action": "shell", "command": "print('must-not-run')"}, {"action": "finish", "summary": "blocked"})
        self.send("پروژه را چک کن و درست کن")
        self.assertNotIn("must-not-run'", self.chat_text().replace("print('must-not-run')", ""))
        self.assertIn("کار خودکار تمام شد", self.chat_text())

    # ---- execution guard (Task 004): tools_mode=off / Competitive Safe hold on every path
    def test_tools_mode_off_blocks_every_registry_tool(self):
        agent = self.win.tool_agent
        self.win.settings["tools_mode"] = "off"
        blocked = agent.registry.execute("get_datetime", {})
        self.assertEqual(blocked.status, "denied")
        self.assertIn("خاموش", blocked.text)
        self.win.settings["tools_mode"] = "auto"
        allowed = agent.registry.execute("get_datetime", {})
        self.assertNotEqual(allowed.status, "denied")           # the allowed path is unchanged

    def test_auto_mission_refuses_when_tools_mode_is_off(self):
        self.prepare_auto()
        self.win.settings["tools_mode"] = "off"
        self.cc.start_auto("کل پروژه را چک کن")
        self.assertIn("خاموش", self.chat_text())
        self.assertIsNone(self.cc.job)
        self.assertFalse(self.win.busy)

    def test_auto_mission_refuses_in_competitive_safe_mode(self):
        self.prepare_auto()
        self.win.tool_agent.set_competitive_safe_mode(True)
        self.cc.start_auto("کل پروژه را چک کن")
        self.assertIn("Competitive Safe", self.chat_text())
        self.assertIsNone(self.cc.job)
        self.assertFalse(self.win.busy)

    def test_direct_run_is_blocked_by_tools_off_and_competitive_safe(self):
        self.turn_on()
        self.cc.shell = (sys.executable, ["-c"])
        self.win.settings["tools_mode"] = "off"
        self.cc.run_command("print('must-not-run')")
        self.assertIn("خاموش", self.chat_text())
        self.assertIsNone(self.cc.proc)                         # no QProcess was started
        self.win.settings["tools_mode"] = "auto"
        self.win.tool_agent.set_competitive_safe_mode(True)
        self.cc.run_command("print('must-not-run')")
        self.assertIn("Competitive Safe", self.chat_text())
        self.assertIsNone(self.cc.proc)

    # ---- local commands
    def test_files_command(self):
        self.turn_on()
        self.send("/files")
        self.assertIn("app.py", self.chat_text())

    def test_run_needs_confirmation_and_shows_output(self):
        self.turn_on()
        self.cc.shell = (sys.executable, ["-c"])
        self.cc.confirm = lambda *a, **k: False
        self.send("/run print('hello-from-run')")
        self.assertNotIn("hello-from-run", self.chat_text().replace("print('hello-from-run')", ""))
        self.cc.confirm = lambda *a, **k: True
        self.win.input.setText("/run print('hello-from-run')")
        self.win.send_message()
        self.assertTrue(pump(lambda: not self.win.busy and "کد خروج: 0" in self.chat_text(), 15))
        self.assertIn("hello-from-run", self.chat_text())

    def test_run_is_unavailable_without_a_shell(self):
        self.turn_on()
        self.cc.shell = None
        self.send("/run dir")
        self.assertIn("Windows", self.chat_text())

    # ---- links
    def test_web_links_still_open_in_the_browser(self):
        with mock.patch("kira.main.QDesktopServices.openUrl") as opened:
            self.win.on_chat_link(QUrl("https://example.com/x"))
            opened.assert_called_once()
            self.win.on_chat_link(QUrl("file:///C:/Windows/system32/calc.exe"))
            opened.assert_called_once()                       # anything else is ignored

    def test_project_folder_survives_a_restart(self):
        self.turn_on()
        from kira.chat_code_ui import CodeChat
        again = CodeChat(self.win)
        self.assertEqual(again.root, self.proj.resolve())

    def test_changing_the_folder_in_words(self):
        self.turn_on()
        other = Path(tempfile.mkdtemp())
        self.cc.pick_folder = lambda: str(other)
        self.send("پوشه پروژه رو عوض کن")
        self.assertEqual(self.cc.root, other.resolve())

    # ---- ZWNJ (نیم‌فاصله) wording and first-run ordering
    def test_zwnj_folder_request_on_first_run_asks_for_the_folder_and_starts_no_mission(self):
        asked = []
        self.cc.pick_folder = lambda: (asked.append(1), str(self.proj))[1]
        with mock.patch.object(self.cc, "start_auto") as started:
            self.send("پوشه‌ی پروژه را عوض کن")
        self.assertEqual(asked, [1])
        self.assertEqual(self.cc.root, self.proj.resolve())
        started.assert_not_called()                            # never a coding mission before the folder exists

    def test_long_folder_request_switches_project_without_a_mission(self):
        self.turn_on()
        other = Path(tempfile.mkdtemp())
        self.cc.pick_folder = lambda: str(other)
        text = ("لطفاً پوشه‌ی پروژه را عوض کن چون می‌خواهم از این به بعد روی یک پروژه‌ی دیگر کار کنم "
                "و مأموریت قبلی را ادامه نده")
        self.assertGreaterEqual(len(text), 80)                 # parse_request leaves long messages alone; the route guard decides
        with mock.patch.object(self.cc, "start_auto") as started:
            self.send(text)
        self.assertEqual(self.cc.root, other.resolve())
        started.assert_not_called()


if __name__ == "__main__":
    unittest.main()
