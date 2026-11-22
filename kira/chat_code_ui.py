"""Kode: one chat-facing coding subsystem with analysis, safe patching and autonomous execution.

No button and no mode: Kira's tab decides from the wording whether a message is a coding mission (agent on a copy of the
project, ends with a zip), a question about the project (read-only investigation) or ordinary talk (normal chat).
Nothing is written to the original project and no command runs without the approvals described in auto_agent.py.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QObject, QProcess, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import characters
from . import chat_code as cc
from .chat_render import message_html
from .auto_agent import KodeAutonomousEngine, MAX_STEPS, guard_reason
from .brain import route_for
from .code_agent import project_tree
from .config import save_settings, DATA_DIR
from .memory import recent_messages

COMMAND_TIMEOUT_MS = 120_000
MAX_TURNS = 12


class _Job(QThread):
    chunk = Signal(str)
    done = Signal(object)
    failed = Signal(str)
    approval = Signal(str, object)                 # (command, holder): the UI thread asks the person and fills holder["ok"]

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.chunk.emit))
        except Exception as exc:  # noqa: BLE001 - shown in the chat, never crashes the app
            self.failed.emit(f"{type(exc).__name__}: {exc}"[:800])


class Kode(QObject):
    """Unified coding workspace for Kira: analysis, reviewed patches and autonomous project missions."""

    def __init__(self, win):
        super().__init__(getattr(win, "widget", win))
        self.win = win
        self.patches = cc.PatchStore()
        self.root = None
        self.current_rel = None            # last file talked about: follow-ups like "fix it" refer to it
        self.turns = []                    # this code conversation only (the persona chat is not mixed in)
        self.job = None
        self.proc = None
        self.proc_timer = None
        self.session = None                # the chat session the running job / command belongs to
        self._streamed = 0
        self.auto_stop = False
        self.auto_dir = Path(DATA_DIR) / "kode_output"         # where Kode delivers completed project archives
        self.auto_results = {}
        self._auto_result_seq = 0                               # monotonic ids: never reused after a removal/restart
        self.auto_python = None                                 # tests may override; None = auto-detect
        self.auto_shell = None                                  # tests may override; None = the agent's default (PowerShell on Windows)
        self.shell = self._default_shell()
        saved = str(win.settings.get("code_workspace_path") or "").strip()
        if saved and Path(saved).is_dir():
            self.root = Path(saved).resolve()
        self._bypass = False                    # next submit goes to the normal chat untouched (classifier said CHAT)
        self._classifying = False
        self._class_queue = []
        self._class_job = None
        self._class_jobs = []
        self._class_token = None
        self._vocab_root, self._vocab = None, frozenset()

    # ------------------------------------------------------------ UI
    @staticmethod
    def _default_shell():
        if os.name == "nt":
            return ("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"])
        return None

    # ------------------------------------------------------------ project / mode
    def pick_folder(self):
        start = str(self.root or Path.home())
        return QFileDialog.getExistingDirectory(getattr(self.win, "widget", self.win), "پوشه‌ی پروژه برای Kode", start)

    def confirm(self, title, text, default_no=True):
        answer = QMessageBox.warning(getattr(self.win, "widget", self.win), title, text, QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No if default_no else QMessageBox.Yes)
        return answer == QMessageBox.Yes

    def choose_project(self):
        path = self.pick_folder()
        if not path:
            return False
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            return False
        self.root = resolved
        self.current_rel = None
        self.turns.clear()
        self.patches.clear()
        self.win.settings["code_workspace_path"] = str(resolved)
        self._save()
        return True

    def change_project(self):
        if self.choose_project():
            self._say("system", f"پروژه‌ی کیرا: {self.root}")

    def ensure_project(self, why=""):
        """The folder Kira works in. Asked once, the first time a coding request needs it."""
        if self.root is not None and self.root.is_dir():
            return True
        self._say("system", (why + "\n" if why else "") + "برای کار روی کد، پوشه‌ی پروژه را انتخاب کن (فقط همین پوشه دیده می‌شود).")
        return self.choose_project()

    def vocabulary(self):
        if self.root is not None and self._vocab_root != self.root:
            self._vocab, self._vocab_root = cc.project_vocabulary(self.root), self.root
        return self._vocab

    def _save(self):
        try:
            save_settings(self.win.settings)
        except Exception:  # noqa: BLE001 - a settings write problem must not break the chat
            pass

    def _activity_panel(self):
        """The activity card belongs to the visible conversation, never a background tab."""
        w = self.win
        return w.kode_activity if w.cur is w.front else None

    def _activity_start(self, status):
        panel = self._activity_panel()
        if panel is not None:
            panel.start(status)

    def _activity_update(self, status):
        panel = self._activity_panel()
        if panel is not None:
            panel.update(status)

    def _activity_step(self, status):
        panel = self._activity_panel()
        if panel is not None:
            panel.step(status)

    def _activity_complete(self, status):
        panel = self._activity_panel()
        if panel is not None:
            panel.complete(status)

    def _activity_fail(self, status):
        panel = self._activity_panel()
        if panel is not None:
            panel.fail(status)

    def _activity_reset(self):
        panel = self._activity_panel()
        if panel is not None:
            panel.reset()

    # ------------------------------------------------------------ chat output helpers
    def _as_kira(self, fn):
        """Run fn with Kira's session as the current one (menu actions and links may fire from any tab)."""
        w = self.win
        sess = w.sessions.get("kira")
        if sess is None:
            return
        with w._as(sess):
            fn()

    def _say(self, kind, text):
        self.win.add_chat(kind, text)

    def _bubble(self, kind, body_html, name=None):
        w = self.win
        if name is None:
            name = characters.display_name(w.settings) if kind == "assistant" else ""
        ui_dir = "rtl" if w.settings.get("ui_lang", "fa") == "fa" else "ltr"
        w.chat.append(message_html(kind, name, "", ui_dir, body_html, accent=w.accent()))
        bar = w.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def show_help(self):
        self._as_kira(lambda: self._say("system", cc.HELP_TEXT))

    def show_files(self):
        def go():
            if self.root is None:
                self._say("system", "پروژه‌ای انتخاب نشده؛ /project را بزن.")
                return
            try:
                tree = project_tree(self.root)
            except Exception as exc:  # noqa: BLE001
                self._say("error", f"خواندن پروژه ناموفق بود: {exc}")
                return
            self._bubble("system", cc.code_block_html(tree), name="")
        self._as_kira(go)

    # ------------------------------------------------------------ entry point from MainWindow.submit
    def handle(self, text, voice=False):
        """True when Kira's code side took the message. Kira decides from the wording (and, when unsure, asks the model)
        whether the person wants work on the project; ordinary talk returns False and goes the normal way."""
        w = self.win
        if w._closing:
            return True
        if w.cur.cid != "kira":
            return False
        if self._bypass:
            self._bypass = False
            return False
        if self._classifying:                                   # a decision is still pending: keep the order of messages
            self._class_queue.append((text, voice))
            return True
        if cc.wants_project_location(text):
            w.add_chat("user", text)
            w.save_message("user", text)
            if self.root is not None and self.root.is_dir():
                self._say("system", f"مسیر پوشه‌ی پروژه‌ی فعلی: {self.root}")
            else:
                self._say("system", "هنوز پوشه‌ی پروژه‌ای برای Kode انتخاب نشده؛ برای انتخاب پوشه بگو «پوشه‌ی پروژه را عوض کن».")
            return True
        req = cc.parse_request(text)
        if req.kind in ("files", "project", "apply", "reject", "help", "run", "auto") or req.explicit:
            return self._explicit(req, text)
        intent, sure = cc.classify_intent(text, self.vocabulary() if self.root is not None else frozenset())
        if intent == "chat" and sure:
            return False
        if not sure:
            if self.root is None:
                return False                                    # no project chosen yet: never guess, never nag
            self._classify_async(text, voice)
            return True
        return self._route(text, intent)

    def _explicit(self, req, text):
        w = self.win
        local = req.kind in ("files", "project", "apply", "reject", "help", "run")
        w.add_chat("user", text)
        if not local:
            w.save_message("user", text)
        if req.kind == "help":
            self._say("system", cc.HELP_TEXT)
        elif req.kind == "project":
            self.change_project()
        elif req.kind in ("apply", "reject"):
            last = self.patches.last()
            if last is None:
                self._say("system", "پیشنهاد تغییری در انتظار تأیید نیست.")
            elif req.kind == "apply":
                self.apply(last.pid)
            else:
                self.reject(last.pid)
        elif not self.ensure_project():
            self._say("system", "بدون پوشه‌ی پروژه نمی‌توانم روی کد کار کنم.")
        elif req.kind == "files":
            self.show_files()
        elif req.kind == "run":
            self.run_command(req.command)
        elif req.kind == "auto":
            self.start_auto(req.text, history=self._history())
        else:
            self.start_request(req, text)                       # /patch and /ask: the one-file flow
        return True

    def _history(self):
        """The recent conversation with Kira, so "fix the thing I told you about" has something to refer to."""
        try:
            msgs = recent_messages(10, "kira")
        except Exception:  # noqa: BLE001
            return []
        if msgs and msgs[-1].get("role") == "user":
            msgs = msgs[:-1]                                    # the message being handled is already saved
        return [{"role": m["role"], "content": str(m["content"])[:600]} for m in msgs[-8:]]

    def _route(self, text, intent):
        """A coding request: make sure a project folder exists, then hand it to the agent (task) or the read-only investigation."""
        w = self.win
        if cc.wants_project_change(text):
            # "پوشه‌ی پروژه را عوض کن" (with or without ZWNJ) is a folder request, never a mission:
            # on first run it must only ask for the folder, and later it switches instead of running the agent.
            self.change_project()
            return True
        w.add_chat("user", text)
        w.save_message("user", text)
        if not self.ensure_project():
            self._say("system", "بدون پوشه‌ی پروژه نمی‌توانم این را انجام بدهم؛ هر وقت خواستی دوباره بگو.")
            return True
        self.start_auto(text, readonly=(intent == "question"), history=self._history())
        return True

    # ---- ambiguous wording: one short model call decides (TASK / QUESTION / CHAT)
    def _classify_async(self, text, voice):
        w = self.win
        if w._closing:
            return
        self._classifying = True
        self._activity_start("در حال تشخیص نوع درخواست…")
        token = object()
        self._class_token = token
        session = w.cur                                            # the chat that asked: results must never land in another tab
        try:
            root = self.root
            if root is None or not Path(root).is_dir():             # deleted / moved / invalid project folder
                raise FileNotFoundError(f"project folder unavailable: {root}")
            router = session.client
            if router is None:
                raise RuntimeError("no model router")
            top = sorted(p.name + ("/" if p.is_dir() else "") for p in Path(root).iterdir() if not p.name.startswith("."))[:40]
            prompt = cc.classifier_prompt(Path(root).name, top, self._history(), text)
            job = _Job(lambda chunk: router.chat_stream([{"role": "user", "content": prompt}], cc.CLASSIFY_SYSTEM,
                                                        temperature=0.0, on_chunk=None).get("text", ""), self)
            job._ui_done_callback = lambda answer: self._classified(token, text, voice, answer, session)
            job._ui_failed_callback = lambda _err: self._classified(token, text, voice, None, session)
            job.done.connect(self._relay_job_done)
            job.failed.connect(self._relay_job_failed)
            job.finished.connect(self._on_class_job_finished)
            self._class_job = job
            self._class_jobs.append(job)
            QTimer.singleShot(25_000, lambda: self._classified(token, text, voice, None, session))   # never leave it hanging
            w.status.setText("کیرا در حال فهمیدن درخواستت است…")
            job.start()
        except Exception:  # noqa: BLE001 - a broken project path must end the decision (normal chat), never crash or stay stuck
            self._classified(token, text, voice, None, session)

    def _classified(self, token, text, voice, answer, session=None):
        if getattr(self, "_class_token", None) is not token:
            return                                              # already decided (the timeout and the answer may both arrive)
        if self.win._closing:
            self._class_token = None
            self._classifying = False
            self._class_queue.clear()
            return
        self._class_token = None
        self._classifying = False
        # The classifier may still be running after its 25-second UI timeout.
        # Keep its QThread tracked until its actual finished signal arrives.
        w = self.win
        intent = cc.parse_classification(answer)
        queued, self._class_queue = self._class_queue, []
        if w._closing:
            return
        session = w.cur if session is None else session
        if session.cid not in w.sessions:
            return                                              # the chat was closed while deciding: nothing to leak into
        with w._as(session):                                    # decide / answer in the chat that asked, even from another tab
            if intent in ("task", "question"):
                self._route(text, intent)
            else:
                self._activity_reset()
                self._bypass = True
                w._voice_next = voice
                try:
                    w.submit(text)
                finally:
                    self._bypass = False                        # (if the message was only queued, it is classified afresh later)
            for t, v in queued:                                 # messages typed while we were deciding, in order
                w._voice_next = v
                w.submit(t)

    # ------------------------------------------------------------ ask / patch
    def _begin_busy(self):
        w = self.win
        self.session = w.cur
        w.busy = True
        w.gen_stop_btn.show()
        w.set_status("st_thinking")

    def _end_busy(self):
        w = self.win
        w.finish_request(None)
        w._send_next_pending()

    def start_request(self, req, raw):
        w = self.win
        if w._closing:
            return
        self._activity_start("در حال جست‌وجوی فایل‌های مرتبط…")
        try:
            files, problems = cc.resolve_files(self.root, req.mentions, cc.explicit_mentions(raw))
        except Exception as exc:  # noqa: BLE001
            self._say("error", f"خواندن پروژه ناموفق بود: {exc}")
            return
        if problems:
            self._activity_step("برخی فایل‌های درخواستی پیدا نشدند")
            self._say("system", "\n".join(problems))
        if not files and self.current_rel:                      # a follow-up ("fix it", "explain more") keeps the same file
            try:
                files = [cc.safe_project_file(self.root, self.current_rel)]
            except Exception:  # noqa: BLE001
                self.current_rel = None
        if req.kind == "patch":
            if not files:
                self._activity_fail("برای پیشنهاد تغییر، فایل مشخصی لازم است")
                self._say("system", "برای تغییر باید فایل را مشخص کنی؛ اسمش را با @ بنویس، مثل @app.py")
                return
            if len(files) > 1:
                self._activity_fail("برای پیشنهاد تغییر، هر بار یک فایل را انتخاب کن")
                self._say("system", "برای تغییر، هر بار فقط یک فایل؛ فایل را مشخص کن. (برای تحلیل چند فایل می‌شود.)")
                return
            blocker = cc.patch_blocker(self.root, files[0])
            if blocker:
                self._say("system", blocker)
                req.kind = "ask"                                # still answer: analysis is allowed
        try:
            context = cc.build_multi_context(self.root, files)
            target = files[0] if files else None
            base_bytes = target.read_bytes() if (target is not None and req.kind == "patch") else None
            rel = target.resolve().relative_to(self.root).as_posix() if target is not None else None
        except Exception as exc:  # noqa: BLE001
            self._activity_fail("خواندن فایل‌های پروژه ناموفق بود")
            self._say("error", str(exc))
            return
        if rel:
            self.current_rel = rel
        engine = cc.KodeEngine(w.cur.client, ui_design_guidance_enabled=bool(w.settings.get("ui_design_guidance_enabled", True)))
        history = list(self.turns)
        question = req.text
        if req.kind == "patch":
            fn = lambda chunk: engine.propose_replacement(question, context, chunk)  # noqa: E731
            done = lambda result: self._patch_done(rel, base_bytes, result, question)  # noqa: E731
        else:
            fn = lambda chunk: engine.ask(question, context, chunk, history=history)  # noqa: E731
            done = lambda result: self._answer_done(question, result)  # noqa: E731
        self._begin_busy()
        self._activity_update("در حال تحلیل کد…" if req.kind != "patch" else "در حال آماده‌سازی پیشنهاد تغییر…")
        sess = self.session
        job = _Job(fn, self)
        self._streamed = 0
        job._ui_chunk_callback = lambda piece: self._progress(sess, piece)
        job._ui_done_callback = lambda result: self._finished(sess, done, result)
        job._ui_failed_callback = lambda error: self._failed(sess, error)
        job.chunk.connect(self._relay_job_chunk)
        job.done.connect(self._relay_job_done)
        job.failed.connect(self._relay_job_failed)
        job.finished.connect(self._job_cleanup)
        self.job = job
        job.start()

    @Slot(str)
    def _relay_job_chunk(self, piece):
        job = self.sender()
        callback = getattr(job, "_ui_chunk_callback", None) if job is not None else None
        if callback is not None:
            callback(piece)

    @Slot(object)
    def _relay_job_done(self, result):
        job = self.sender()
        callback = getattr(job, "_ui_done_callback", None) if job is not None else None
        if callback is not None:
            callback(result)

    @Slot(str)
    def _relay_job_failed(self, error):
        job = self.sender()
        callback = getattr(job, "_ui_failed_callback", None) if job is not None else None
        if callback is not None:
            callback(error)

    @Slot()
    def _on_class_job_finished(self):
        job = self.sender()
        if job is None:
            return
        if job in self._class_jobs:
            self._class_jobs.remove(job)
        if self._class_job is job:
            self._class_job = None
        job.deleteLater()

    def _progress(self, sess, piece):
        self._streamed += len(piece)
        w = self.win
        if sess is w.front:
            w.status.setText("کیرا در حال بررسی کد است…")
            self._activity_update("در حال تحلیل کد و آماده‌سازی پاسخ…")

    @Slot()
    def _job_cleanup(self):
        job = self.sender()
        if job is self.job or job is None:
            self.job = None
        if job is not None:
            job.deleteLater()                                # never delete a newer job that replaced this one

    def _finished(self, sess, done, result):
        w = self.win
        if w._closing or sess.cid not in w.sessions:
            return
        with w._as(sess):
            try:
                done(result)
            except Exception as exc:  # noqa: BLE001
                w.add_chat("error", f"Kode: {exc}")
                self._activity_fail("پردازش با خطا متوقف شد")
            self._end_busy()

    def _failed(self, sess, error):
        w = self.win
        if w._closing or sess.cid not in w.sessions:
            return
        with w._as(sess):
            w.add_chat("error", f"Kode: {error}")
            self._activity_fail("پردازش با خطا متوقف شد")
            self._end_busy()

    def _remember(self, user_text, answer):
        self.turns += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        del self.turns[:-MAX_TURNS]

    def _answer_done(self, question, answer):
        self._bubble("assistant", cc.answer_html(answer))
        self._activity_complete("تحلیل تمام شد")
        self.win.save_message("assistant", answer)
        self._remember(question, answer)

    def _patch_done(self, rel, base_bytes, replacement, question):
        try:
            base_text = base_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self._say("error", "فایل متن UTF-8 نیست.")
            return
        replacement = cc.match_newlines(base_text, replacement)
        diff = cc.make_diff(rel, base_text, replacement)
        if not diff:
            self._say("assistant", "مدل تغییری پیشنهاد نکرد؛ فایل همان است که بود.")
            self._activity_complete("تغییری لازم نبود")
            return
        patch = self.patches.add(rel, replacement, base_bytes)
        self._bubble("assistant", cc.patch_card_html(patch, diff))
        self._activity_complete("پیشنهاد تغییر آماده است؛ منتظر تأیید تو")
        note = (f"پیشنهاد تغییر برای {rel} آماده شد (Diff بالا در چت). "
                "هنوز هیچ فایلی تغییر نکرده؛ تا تأیید تو اعمال نمی‌شود.")
        self.win.save_message("assistant", note)
        self._remember(question, note)

    # ------------------------------------------------------------ approve / reject
    def on_link(self, url: QUrl):
        action, pid = url.host().lower(), url.path().lstrip("/")

        def go():
            if action == "apply":
                self.apply(pid)
            elif action == "reject":
                self.reject(pid)
            elif action == "open":                              # reveal a delivered zip's folder (only paths we created)
                zip_path = self.auto_results.get(pid)
                if zip_path is not None and Path(zip_path).exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(zip_path).parent)))
        self._as_kira(go)

    def apply(self, pid):
        patch = self.patches.get(pid)
        if patch is None:
            self._say("system", "این پیشنهاد دیگر معتبر نیست (قبلاً اعمال یا رد شده، یا برنامه دوباره باز شده).")
            return
        if self.root is None:
            self._say("error", "پوشه‌ی پروژه دیگر انتخاب نشده است.")
            return
        if not self.confirm("تأیید اعمال تغییر",
                            f"فایل «{patch.rel}» با پیشنهاد کیرا بازنویسی می‌شود. "
                            "یک نسخه‌ی پشتیبان از فایل اصلی نگه داشته می‌شود.\n\nاعمال شود؟", default_no=False):
            self._say("system", "اعمال لغو شد؛ پیشنهاد هنوز در انتظار است.")
            return
        try:
            cc.apply_patch(self.root, patch)
        except Exception as exc:  # noqa: BLE001
            self._say("error", f"اعمال ناموفق بود: {exc}")
            return
        self.patches.pop(pid)
        self._say("system", f"✅ تغییر روی {patch.rel} با تأیید تو اعمال شد؛ نسخه‌ی پشتیبان فایل اصلی نگه داشته شد.")

    def reject(self, pid):
        if self.patches.pop(pid) is None:
            self._say("system", "این پیشنهاد دیگر در انتظار نیست.")
            return
        self._say("system", "پیشنهاد رد شد؛ هیچ فایلی تغییر نکرد.")

    # ------------------------------------------------------------ /auto
    @Slot(str, object)
    def _ask_approval(self, command, holder):
        """Runs in the UI thread (queued from the agent thread): one question per dangerous command, default = No."""
        if self.win._closing or self.auto_stop:
            holder["ok"] = False
            holder["event"].set()
            return
        holder["ok"] = bool(self.confirm("تأیید دستور کیرا",
                                         "کیرا می‌خواهد این را اجرا کند (روی نسخه‌ی کاری، ولی PowerShell می‌تواند بیرون از آن هم اثر بگذارد):\n\n"
                                         + str(command)[:1200] + "\n\nفقط در صورت اطمینان تأیید کن."))
        holder["event"].set()

    def start_auto(self, goal, readonly=False, history=None):
        w = self.win
        if not goal:
            self._say("system", "بعد از /auto مأموریت را بنویس، مثلاً: /auto کل پروژه را چک کن، باگ‌ها را درست کن و تست‌ها را بزن")
            return
        tool_agent = getattr(w, "tool_agent", None)
        guard = getattr(getattr(tool_agent, "registry", None), "execution_guard", None)
        if tool_agent is not None and tool_agent.mode() == "off":
            self._say("system", "ابزارها خاموش است (tools_mode = off)؛ مأموریت خودکار اجرا نمی‌شود. "
                                "برای اجرا، حالت ابزارها را در تنظیمات از Off خارج کن.")
            return
        denied = guard_reason(guard, "read" if readonly else "run")
        if denied:                                             # e.g. Competitive Safe blocks local tools: never start
            self._say("system", str(denied))
            return
        if not readonly and not self.confirm(
                "تأیید مأموریت خودکار",
                "کیرا روی یک کپی از پروژه کار می‌کند (فایل‌های حساس کپی نمی‌شوند) و پروژه‌ی اصلی تغییر نمی‌کند. "
                "برای تست ممکن است کد پایتون خود پروژه را اجرا کند؛ این کدها با دسترسی حساب ویندوز تو اجرا می‌شوند و sandbox نیستند. "
                "هر ویرایش Python به‌طور خودکار با Ruff/Pyflakes بررسی می‌شود؛ برنامه‌ریز، مجری و بازبین ممکن است از نقش‌های جداگانه‌ی Route استفاده کنند. "
                f"هر دستور PowerShell جداگانه از تو تأیید می‌گیرد. حداکثر {MAX_STEPS} گام و با Stop قابل توقف است. آخرش یک زیپ تحویل می‌دهد.\n\nشروع شود؟"):
            self._say("system", "مأموریت لغو شد.")
            return
        self.auto_stop = False
        job_box = {}

        def approve(command):
            holder = {"ok": False, "event": threading.Event()}
            job_box["job"].approval.emit(command, holder)
            while not holder["event"].wait(0.3):               # waiting for the person; Stop counts as "no"
                if self.auto_stop:
                    return False
            return holder["ok"]

        agent = KodeAutonomousEngine(w.cur.client, self.root, goal, should_stop=lambda: self.auto_stop, python=self.auto_python,
                          output_dir=self.auto_dir, readonly=readonly, approve=approve,
                          max_steps=15 if readonly else MAX_STEPS, shell=self.auto_shell, history=history,
                          plan_route_id=route_for("deep", w.settings),
                          exec_route_id=route_for("surface", w.settings),
                          review_route_id=route_for("reflection", w.settings),
                          execution_guard=guard,
                          ui_design_guidance_enabled=bool(w.settings.get("ui_design_guidance_enabled", True)))
        self._begin_busy()
        self._activity_start("در حال بررسی پروژه و ساخت برنامهٔ کار…" if readonly else "در حال تحلیل پروژه و برنامه‌ریزی تغییرات…")
        sess = self.session
        job = _Job(lambda chunk: (setattr(agent, "emit", chunk), agent.run())[1], self)
        job_box["job"] = job
        job._ui_chunk_callback = lambda line: self._auto_event(sess, line)
        job._ui_done_callback = lambda result: self._finished(
            sess, lambda r: self._auto_done(goal, r), result
        )
        job._ui_failed_callback = lambda error: self._failed(sess, error)
        job.chunk.connect(self._relay_job_chunk)
        job.approval.connect(self._ask_approval)
        job.done.connect(self._relay_job_done)
        job.failed.connect(self._relay_job_failed)
        job.finished.connect(self._job_cleanup)
        self.job = job
        w.status.setText("کیرا در حال بررسی پروژه است…" if readonly else "کیرا در حال کار خودکار روی پروژه است…")
        job.start()

    @staticmethod
    def _activity_label(line):
        """Translate internal tool event labels into concise, user-facing progress."""
        text = str(line or "").strip().lstrip("• ").strip()
        if not text:
            return ""
        if text.startswith("گام "):
            text = text.split(":", 1)[-1].strip()
        return text[:140]

    def _auto_event(self, sess, line):
        w = self.win
        if w._closing or sess.cid not in w.sessions:
            return
        with w._as(sess):
            self._activity_step(self._activity_label(line))

    def _store_auto_result(self, zip_path):
        """Register one delivered ZIP under a stable, monotonic id (never len()+1)."""
        self._auto_result_seq += 1
        rid = str(self._auto_result_seq)
        self.auto_results[rid] = Path(zip_path)
        while len(self.auto_results) > 100:                     # bounded: old links stop working instead of leaking memory
            self.auto_results.pop(next(iter(self.auto_results)))
        return rid

    def _auto_done(self, goal, result):
        w = self.win
        if result.get("readonly"):
            self._activity_complete("بررسی پروژه تمام شد")
            self._bubble("assistant", cc.answer_html(result["summary"]))
            w.save_message("assistant", result["summary"])
            self._remember(goal, result["summary"])
            return
        if not result.get("zip"):
            self._activity_fail("مأموریت به خروجی نهایی نرسید")
            changed = result.get("changed") or []
            lines = ["مأموریت خودکار به تحویل نهایی نرسید.", "", result.get("summary") or "نتیجه تأیید نشده است."]
            if result.get("resume_available"):
                lines.append("وضعیت و نسخه‌ی کاری ذخیره شد؛ اجرای دوباره‌ی همین درخواست از آخرین checkpoint ادامه پیدا می‌کند.")
            if changed:
                lines.extend(["", "تغییرات انجام‌شده فقط در نسخه‌ی کاری موقت بوده‌اند و ZIP نهایی ساخته نشده:", "، ".join(changed[:20])])
            body = cc.answer_html("\\n".join(lines))
            self._bubble("assistant", body)
            w.save_message("assistant", "\\n".join(lines))
            self._remember("/auto " + goal, result.get("summary") or "مأموریت ناتمام")
            return
        self._activity_complete("تغییرات بررسی و بستهٔ خروجی آماده شد")
        zip_path = Path(result["zip"])
        rid = self._store_auto_result(zip_path)
        changed = result["changed"]
        runs = result["runs"]
        lines = [f"کار خودکار تمام شد ({result['steps']} گام).", "", result["summary"], ""]
        lines.append("فایل‌های تغییرکرده: " + (("، ".join(changed[:15]) + (f" و {len(changed) - 15} مورد دیگر" if len(changed) > 15 else "")) if changed else "هیچ"))
        if runs:
            lines.append("اجراها: " + "؛ ".join(f"{a} ← exit {c}" for a, c in runs[-6:]))
        if result.get("external"):
            lines.append(f"⚠ هشدار: {len(result['external'])} فایل پروژه‌ی اصلی هم‌زمان بیرون از Kode عوض شده؛ جزئیات در KODE_REPORT.md داخل زیپ.")
        info = result.get("zip_info") or {}
        lines.append(f"زیپ سالم است ({info.get('files', '?')} فایل): {zip_path}")
        body = cc.answer_html("\n".join(lines)) + (
            f'<p dir="rtl" align="right" style="margin:4px 0;"><a href="kode://open/{rid}" style="color:#7ee787;">📂 باز کردن پوشه‌ی زیپ</a></p>')
        self._bubble("assistant", body)
        w.save_message("assistant", "\n".join(lines))
        self._remember("/auto " + goal, result["summary"])

    # ------------------------------------------------------------ /run
    def run_command(self, command):
        w = self.win
        command = str(command or "").strip()
        if not command:
            self._say("system", "بعد از /run دستور را بنویس.")
            return
        tool_agent = getattr(w, "tool_agent", None)
        guard = getattr(getattr(tool_agent, "registry", None), "execution_guard", None)
        denied = guard_reason(guard, "shell")
        if denied:                                             # tools_mode = off / Competitive Safe: no direct PowerShell either
            self._say("system", str(denied))
            return
        if self.shell is None:
            self._say("system", "اجرای دستور در این نسخه فقط روی Windows (PowerShell) فعال است.")
            return
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self._say("system", "یک دستور هنوز در حال اجراست؛ صبر کن یا Stop را بزن.")
            return
        if not self.confirm("تأیید اجرای دستور",
                            "این دستور با دسترسی حساب ویندوز تو و در پوشه‌ی پروژه اجرا می‌شود. "
                            "دستورات PowerShell می‌توانند خارج از پروژه هم اثر بگذارند.\n\n"
                            + command[:1200] + "\n\nفقط در صورت اطمینان اجرا کن."):
            self._say("system", "اجرای دستور لغو شد.")
            return
        program, args = self.shell
        proc = QProcess(self)
        proc.setWorkingDirectory(str(self.root))
        proc.setProgram(program)
        proc.setArguments(list(args) + [command])
        proc.setProcessChannelMode(QProcess.MergedChannels)
        out = []
        proc.readyReadStandardOutput.connect(lambda: out.append(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")))
        sess = w.cur
        proc.finished.connect(lambda code, status: self._command_done(sess, proc, command, out, code))
        proc.errorOccurred.connect(lambda error: self._command_error(sess, proc, error))
        self.proc = proc
        self._begin_busy()
        self._activity_start("در حال اجرای دستور در پوشهٔ پروژه…")
        self.proc_timer = QTimer(self)
        self.proc_timer.setSingleShot(True)
        self.proc_timer.timeout.connect(proc.kill)
        self.proc_timer.start(COMMAND_TIMEOUT_MS)
        proc.start()

    def _stop_timer(self):
        if self.proc_timer is not None:
            self.proc_timer.stop()
            self.proc_timer = None

    def _command_done(self, sess, proc, command, out, code):
        self._stop_timer()
        out.append(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))
        self.proc = None
        proc.deleteLater()
        w = self.win
        if w._closing or sess.cid not in w.sessions:
            return
        with w._as(sess):
            self._bubble("system", cc.output_html(command, "".join(out).rstrip(), code), name="")
            self._activity_complete("اجرای دستور تمام شد" if code == 0 else f"دستور با کد خروج {code} تمام شد")
            self._end_busy()

    def _command_error(self, sess, proc, error):
        if self.proc is not proc or proc.state() != QProcess.NotRunning:
            return                                           # a crash / kill is reported by `finished`; this is a start failure
        self._stop_timer()
        self.proc = None
        w = self.win
        if not w._closing and sess.cid in w.sessions:
            with w._as(sess):
                w.add_chat("error", f"اجرای دستور ناموفق بود: {error}")
                self._activity_fail("اجرای دستور شروع نشد")
                self._end_busy()
        proc.deleteLater()

    # ------------------------------------------------------------ Stop button / shutdown
    def stop(self, sess):
        """Called by MainWindow.stop_generation. True = a running command was killed (nothing else to cancel)."""
        if self.job is not None and self.session is sess:
            self._activity_update("در حال متوقف‌کردن عملیات…")
            self.auto_stop = True                              # the auto loop checks this between steps (harmless for other jobs)
        if self.proc is not None and self.session is sess and self.proc.state() != QProcess.NotRunning:
            self._activity_update("در حال متوقف‌کردن دستور…")
            self.proc.kill()
            return True
        return False

    def background_workers(self):
        """Return every classifier/job/process that must exit before the window is destroyed."""
        workers = [*self._class_jobs]
        if self.job is not None:
            workers.append(self.job)
        if self.proc is not None:
            workers.append(self.proc)
        return workers

    def shutdown(self):
        """Request cancellation without waiting on the GUI thread."""
        self.auto_stop = True
        self._stop_timer()
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
        for class_job in list(self._class_jobs):
            if class_job.isRunning():
                class_job.requestInterruption()
        if self.job is not None and self.job.isRunning():
            self.job.requestInterruption()                   # Kode checks should_stop between steps


# Backward-compatible name for older composition roots.
CodeChat = Kode
