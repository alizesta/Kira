"""Ai1 Code workspace UI: project browser, editor, explicit PowerShell terminal and approval-gated Code Agent proposals."""
from __future__ import annotations

import os
import difflib
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QProcess, QDir
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget, QLabel, QPushButton,
    QTreeView, QFileSystemModel, QPlainTextEdit, QLineEdit, QTextBrowser,
    QFileDialog, QMessageBox, QInputDialog, QGroupBox, QFormLayout, QProgressBar, QDialogButtonBox,
)

from .code_agent import CodeAgentEngine, build_project_context, safe_project_file, SKIP_DIRS
from .hybrid_ai import HybridRouter


class _CodeAskWorker(QThread):
    chunk = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, engine, request, context, mode="ask", parent=None):
        super().__init__(parent)
        self.engine, self.request, self.context, self.mode = engine, request, context, mode

    def run(self):
        try:
            answer = (self.engine.propose_replacement(self.request, self.context, self.chunk.emit)
                       if self.mode == "patch" else self.engine.ask(self.request, self.context, self.chunk.emit))
            self.done.emit(answer)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc)[:800])


class CodeWorkspaceDialog(QDialog):
    """Separate engineering workspace. Agent proposes edits; workspace writes only after explicit approval. Commands are always user initiated."""
    def __init__(self, settings, router, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.router = HybridRouter(settings)
        self.engine = CodeAgentEngine(self.router)
        self.project_root = None
        self.current_file = None
        self._file_original_bytes = None
        self._patch_base_text = None
        self._pending_patch = None
        self._worker = None
        self._agent_stream_buffer = ""
        self._process = None
        self._closing = False
        self.setWindowTitle("Ai1 Code")
        self.resize(1180, 780)
        self.setMinimumSize(800, 560)
        self._build_ui()
        saved = str(self.settings.get("code_workspace_path") or "").strip()
        if saved and Path(saved).is_dir():
            self.set_project(saved)

    def _build_ui(self):
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.project_label = QLabel("پروژه‌ای انتخاب نشده")
        self.project_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.open_project_btn = QPushButton("باز کردن پروژه")
        self.open_project_btn.clicked.connect(self.choose_project)
        self.refresh_btn = QPushButton("بازخوانی فایل‌ها")
        self.refresh_btn.clicked.connect(self.refresh_tree)
        header.addWidget(self.project_label, 1)
        header.addWidget(self.open_project_btn)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(QLabel("فایل‌های پروژه"))
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setReadOnly(True)
        self.fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.clicked.connect(self.open_tree_file)
        left_l.addWidget(self.tree, 1)
        split.addWidget(left)

        right = QSplitter(Qt.Vertical)
        editor_box = QWidget()
        editor_l = QVBoxLayout(editor_box)
        editor_l.setContentsMargins(0, 0, 0, 0)
        editor_head = QHBoxLayout()
        self.file_label = QLabel("فایلی باز نیست")
        self.save_file_btn = QPushButton("ذخیره فایل")
        self.save_file_btn.clicked.connect(self.save_current_file)
        self.save_file_btn.setEnabled(False)
        editor_head.addWidget(self.file_label, 1)
        editor_head.addWidget(self.save_file_btn)
        editor_l.addLayout(editor_head)
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setPlaceholderText("از درخت پروژه یک فایل متنی انتخاب کن…")
        self.editor.document().modificationChanged.connect(self._editor_modified)
        editor_l.addWidget(self.editor, 1)
        right.addWidget(editor_box)

        bottom = QWidget()
        bottom_l = QVBoxLayout(bottom)
        bottom_l.setContentsMargins(0, 0, 0, 0)
        agent_box = QGroupBox("Code Agent · تحلیل و پیشنهاد تغییر")
        agent_l = QVBoxLayout(agent_box)
        self.agent_output = QTextBrowser()
        self.agent_output.setOpenExternalLinks(False)
        self.agent_output.setPlaceholderText("درخواست تحلیل، بررسی خطا یا توضیح کد را بنویس…")
        agent_l.addWidget(self.agent_output, 1)
        agent_row = QHBoxLayout()
        self.agent_input = QLineEdit()
        self.agent_input.setPlaceholderText("مثلاً: علت این خطا را پیدا کن و راه‌حل کم‌ریسک پیشنهاد بده")
        self.agent_input.returnPressed.connect(self.ask_agent)
        self.ask_btn = QPushButton("تحلیل")
        self.ask_btn.clicked.connect(self.ask_agent)
        self.patch_btn = QPushButton("پیشنهاد تغییر")
        self.patch_btn.clicked.connect(self.propose_patch)
        agent_row.addWidget(self.agent_input, 1)
        agent_row.addWidget(self.ask_btn)
        agent_row.addWidget(self.patch_btn)
        agent_l.addLayout(agent_row)
        self.agent_progress = QProgressBar()
        self.agent_progress.setRange(0, 0)
        self.agent_progress.hide()
        agent_l.addWidget(self.agent_progress)
        bottom_l.addWidget(agent_box, 3)

        terminal_box = QGroupBox("PowerShell · اجرای دستی")
        terminal_l = QVBoxLayout(terminal_box)
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setMaximumBlockCount(2000)
        self.terminal_output.setMaximumHeight(130)
        self.terminal_output.setFont(QFont("Consolas", 9))
        terminal_l.addWidget(self.terminal_output)
        command_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("دستور PowerShell را بنویس؛ اجرای دستور همیشه با تأیید توست")
        self.command_input.returnPressed.connect(self.run_command)
        self.run_command_btn = QPushButton("اجرا…")
        self.run_command_btn.clicked.connect(self.run_command)
        command_row.addWidget(self.command_input, 1)
        command_row.addWidget(self.run_command_btn)
        terminal_l.addLayout(command_row)
        bottom_l.addWidget(terminal_box, 2)
        right.addWidget(bottom)
        right.setSizes([400, 340])
        split.addWidget(right)
        split.setSizes([260, 900])
        root.addWidget(split, 1)

        self.status_label = QLabel("آماده")
        root.addWidget(self.status_label)

    def update_runtime(self, settings, router):
        self.settings = settings
        self.router = HybridRouter(settings)
        self.engine = CodeAgentEngine(self.router)

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(self, "انتخاب پوشه پروژه", str(self.project_root or Path.home()))
        if path:
            self.set_project(path)

    def set_project(self, path):
        try:
            resolved = Path(path).expanduser().resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError("مسیر انتخاب‌شده پوشه نیست.")
        except Exception as exc:
            QMessageBox.warning(self, "Ai1 Code", str(exc))
            return
        self.project_root = resolved
        self.current_file = None
        self._file_original_bytes = None
        self._pending_patch = None
        self.editor.clear()
        self.editor.document().setModified(False)
        self.file_label.setText("فایلی باز نیست")
        self.save_file_btn.setEnabled(False)
        self.project_label.setText(str(resolved))
        self.fs_model.setRootPath(str(resolved))
        self.tree.setRootIndex(self.fs_model.index(str(resolved)))
        self.settings["code_workspace_path"] = str(resolved)
        try:
            from .config import save_settings
            save_settings(self.settings)
        except Exception:
            pass
        self.status_label.setText("پروژه بارگذاری شد")

    def refresh_tree(self):
        if self.project_root and self.project_root.is_dir():
            self.fs_model.setRootPath("")
            self.fs_model.setRootPath(str(self.project_root))
            self.tree.setRootIndex(self.fs_model.index(str(self.project_root)))
            self.status_label.setText("درخت فایل‌ها تازه‌سازی شد")

    def open_tree_file(self, index):
        path = Path(self.fs_model.filePath(index))
        if path.is_dir():
            return
        try:
            target = safe_project_file(self.project_root, path)
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            QMessageBox.information(self, "Ai1 Code", "این فایل متن UTF-8 نیست.")
            return
        except Exception as exc:
            QMessageBox.warning(self, "Ai1 Code", str(exc))
            return
        if self.editor.document().isModified():
            answer = QMessageBox.question(
                self, "تغییر ذخیره‌نشده",
                "تغییرات فایل فعلی ذخیره نشده‌اند. بدون ذخیره باز شود؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.current_file = target
        self._file_original_bytes = target.read_bytes()
        self.editor.setPlainText(content)
        self.editor.document().setModified(False)
        self.file_label.setText(target.relative_to(self.project_root).as_posix())
        self.save_file_btn.setEnabled(True)

    def _editor_modified(self, modified):
        self.save_file_btn.setEnabled(bool(self.current_file))
        if self.current_file:
            base = self.current_file.relative_to(self.project_root).as_posix()
            self.file_label.setText(base + ("  • تغییر دارد" if modified else ""))

    def save_current_file(self):
        if not self.current_file or not self.project_root:
            return
        try:
            target = safe_project_file(self.project_root, self.current_file)
            if target != self.current_file.resolve(strict=True):
                raise ValueError("مسیر فایل تغییر کرده است.")
            text = self.editor.toPlainText()
            if len(text.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("ذخیره فایل‌های بزرگ‌تر از ۲ مگابایت در این نسخه پشتیبانی نمی‌شود.")
            backup = target.with_name(target.name + ".ai1code.bak")
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            temp = target.with_name(target.name + ".ai1code.tmp")
            temp.write_text(text, encoding="utf-8", newline="")
            temp.replace(target)
            self.editor.document().setModified(False)
            self._file_original_bytes = target.read_bytes()
            self.status_label.setText("فایل ذخیره شد؛ نسخه پشتیبان کنار فایل باقی ماند.")
        except Exception as exc:
            QMessageBox.critical(self, "ذخیره ناموفق", str(exc))

    def ask_agent(self):
        self._start_agent_request("ask")

    def propose_patch(self):
        self._start_agent_request("patch")

    def _start_agent_request(self, mode):
        request = self.agent_input.text().strip()
        if not request or not self.project_root:
            if not self.project_root:
                QMessageBox.information(self, "Ai1 Code", "اول پوشه پروژه را انتخاب کن.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if mode == "patch" and not self.current_file:
            QMessageBox.information(self, "Ai1 Code", "برای پیشنهاد تغییر، اول یک فایل متنی را باز کن.")
            return
        try:
            selected = self.current_file if self.current_file and self.current_file.exists() else None
            unsaved_text = self.editor.toPlainText() if selected and self.editor.document().isModified() else None
            context = build_project_context(self.project_root, selected, unsaved_text)
        except Exception as exc:
            QMessageBox.warning(self, "Code Agent", str(exc))
            return
        self.agent_input.clear()
        self._agent_stream_buffer = ""
        self._active_mode = mode
        self._patch_base_text = self.editor.toPlainText() if mode == "patch" else None
        self.agent_output.append(f"<b>تو:</b> {request}")
        self.agent_output.append("<b>Code Agent:</b> ")
        self.ask_btn.setEnabled(False)
        self.patch_btn.setEnabled(False)
        self.agent_progress.show()
        self.status_label.setText("Code Agent در حال تحلیل است…")
        worker = _CodeAskWorker(self.engine, request, context, mode, self)
        worker.chunk.connect(self._agent_chunk)
        worker.done.connect(self._patch_done if mode == "patch" else self._agent_done)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(self._agent_finished)
        self._worker = worker
        worker.start()

    def _agent_chunk(self, text):
        self._agent_stream_buffer += text
        cursor = self.agent_output.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.agent_output.setTextCursor(cursor)
        self.agent_output.ensureCursorVisible()

    def _agent_done(self, answer):
        self.status_label.setText("تحلیل کامل شد؛ هیچ فایلی تغییر نکرد.")
        if not self._agent_stream_buffer:
            self.agent_output.append(answer)


    def _patch_done(self, replacement):
        self._pending_patch = replacement
        self.status_label.setText("پیشنهاد آماده است؛ هنوز هیچ فایلی تغییر نکرده.")
        self._show_patch_preview(replacement)

    def _show_patch_preview(self, replacement):
        if not self.current_file:
            return
        old = self.editor.toPlainText()
        rel = self.current_file.relative_to(self.project_root).as_posix()
        diff = "".join(difflib.unified_diff(old.splitlines(True), replacement.splitlines(True),
                                            fromfile=rel + " (current)", tofile=rel + " (proposed)"))
        if not diff:
            QMessageBox.information(self, "Ai1 Code", "مدل تغییری پیشنهاد نکرده است.")
            self._pending_patch = None
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("بازبینی تغییرات پیشنهادی")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("این فقط پیش‌نمایش است. فایل تا زمان تأیید صریح تو تغییر نمی‌کند."))
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("Consolas", 9))
        view.setPlainText(diff)
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox()
        buttons.addButton("تأیید و اعمال تغییر", QDialogButtonBox.AcceptRole)
        buttons.addButton("رد کردن", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(lambda: self._apply_patch(dialog, replacement))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _apply_patch(self, dialog, replacement):
        try:
            if not self.current_file or not self.project_root:
                raise ValueError("فایل انتخاب‌شده دیگر معتبر نیست.")
            target = safe_project_file(self.project_root, self.current_file)
            if target.read_bytes() != self._file_original_bytes:
                raise ValueError("فایل روی دیسک بعد از باز شدن تغییر کرده؛ برای جلوگیری از بازنویسی، Patch لغو شد. فایل را دوباره باز کن.")
            if self.editor.toPlainText() != self._patch_base_text:
                raise ValueError("محتوای ویرایشگر بعد از تولید Patch تغییر کرده؛ پیشنهاد قدیمی اعمال نشد.")
            if len(replacement.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("حجم فایل پیشنهادی از سقف ۲ مگابایت بیشتر است.")
            backup = target.with_name(target.name + ".ai1code.bak")
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            temp = target.with_name(target.name + ".ai1code.tmp")
            temp.write_text(replacement, encoding="utf-8", newline="")
            temp.replace(target)
            self._file_original_bytes = target.read_bytes()
            self.editor.setPlainText(replacement)
            self.editor.document().setModified(False)
            self._pending_patch = None
            self.status_label.setText("Patch با تأیید تو اعمال شد؛ نسخه پشتیبان نگه داشته شد.")
            dialog.accept()
        except Exception as exc:
            QMessageBox.critical(self, "اعمال Patch ناموفق", str(exc))

    def _agent_failed(self, message):
        self.agent_output.append(f"\n<b>خطا:</b> {message}")
        self.status_label.setText("تحلیل ناموفق بود")

    def _agent_finished(self):
        self.ask_btn.setEnabled(True)
        self.patch_btn.setEnabled(True)
        self.agent_progress.hide()
        self._worker = None

    def run_command(self):
        command = self.command_input.text().strip()
        if not command or not self.project_root:
            if not self.project_root:
                QMessageBox.information(self, "Ai1 Code", "اول پوشه پروژه را انتخاب کن.")
            return
        if os.name != "nt":
            QMessageBox.warning(self, "PowerShell", "ترمینال این نسخه فقط روی Windows فعال است.")
            return
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            return
        answer = QMessageBox.warning(
            self, "تأیید اجرای دستور",
            "این دستور با دسترسی حساب ویندوز تو و در مسیر پروژه اجرا می‌شود. دستورات PowerShell می‌توانند خارج از پروژه هم اثر بگذارند.\n\n"
            + command[:1200] + "\n\nفقط در صورت اطمینان اجرا کن.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.command_input.clear()
        self.terminal_output.appendPlainText(f"> {command}")
        process = QProcess(self)
        process.setWorkingDirectory(str(self.project_root))
        process.setProgram("powershell.exe")
        process.setArguments(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command])
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda p=process: self._terminal_read(p))
        process.finished.connect(lambda code, status, p=process: self._terminal_finished(p, code, status))
        process.errorOccurred.connect(lambda error, p=process: self.terminal_output.appendPlainText(f"Process error: {error}"))
        self._process = process
        process.start()
        self.status_label.setText("دستور در حال اجراست…")

    def _terminal_read(self, process):
        data = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self.terminal_output.appendPlainText(data.rstrip())

    def _terminal_finished(self, process, code, _status):
        self._terminal_read(process)
        self.terminal_output.appendPlainText(f"[exit code: {code}]")
        self.status_label.setText(f"دستور تمام شد؛ کد خروج: {code}")
        self._process = None
        process.deleteLater()

    def shutdown(self):
        self._closing = True
        try:
            self.router.cancel()
        except Exception:
            pass
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(1000)
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(1500)

    def closeEvent(self, event):
        if self.editor.document().isModified():
            answer = QMessageBox.question(
                self, "تغییر ذخیره‌نشده", "فایل تغییر ذخیره‌نشده دارد. با بستن محیط، این تغییر از بین می‌رود.",
                QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if answer != QMessageBox.Close:
                event.ignore()
                return
        event.accept()
