"""Standalone Ai1 Code workspace UI.

The workspace reuses CodeChat/AutoAgent for missions and the existing approval-
gated PowerShell runner. It does not create a second shell or permission system.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QPlainTextEdit, QTabWidget, QLineEdit, QPushButton, QLabel, QMessageBox,
    QFileDialog, QInputDialog, QGroupBox,
)

from .code_agent import safe_project_file, SKIP_DIRS, MAX_FILE_BYTES, _is_sensitive


class Ai1CodeWorkspace(QWidget):
    """Project explorer, editor, AI task panel and approval-gated terminal."""

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.code = window.code_chat
        self.root = None
        self.current_file: Path | None = None
        self._original_bytes = b""
        self._dirty = False
        self._refreshing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        project_row = QHBoxLayout()
        self.project_path = QLineEdit()
        self.project_path.setReadOnly(True)
        self.project_path.setPlaceholderText("پوشه‌ی پروژه هنوز انتخاب نشده است")
        self.project_btn = QPushButton("انتخاب پروژه")
        self.refresh_btn = QPushButton("تازه‌سازی")
        self.new_file_btn = QPushButton("فایل جدید")
        self.rename_btn = QPushButton("تغییر نام")
        self.save_btn = QPushButton("ذخیره فایل")
        self.save_btn.setEnabled(False)
        project_row.addWidget(self.project_path, 1)
        project_row.addWidget(self.project_btn)
        project_row.addWidget(self.refresh_btn)
        project_row.addWidget(self.new_file_btn)
        project_row.addWidget(self.rename_btn)
        project_row.addWidget(self.save_btn)
        outer.addLayout(project_row)

        splitter = QSplitter(Qt.Horizontal)
        self.files = QTreeWidget()
        self.files.setHeaderHidden(True)
        self.files.setMinimumWidth(190)
        self.files.setMaximumWidth(330)
        splitter.addWidget(self.files)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        task_box = QGroupBox("Code Agent")
        task_layout = QVBoxLayout(task_box)
        task_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("مأموریت کدنویسی یا سؤال درباره‌ی این پروژه…")
        self.task_btn = QPushButton("اجرای مأموریت")
        self.analyze_btn = QPushButton("تحلیل فقط‌خواندنی")
        self.stop_btn = QPushButton("توقف")
        self.stop_btn.setEnabled(False)
        task_row.addWidget(self.task_input, 1)
        task_row.addWidget(self.task_btn)
        task_row.addWidget(self.analyze_btn)
        task_row.addWidget(self.stop_btn)
        task_layout.addLayout(task_row)
        self.agent_log = QPlainTextEdit()
        self.agent_log.setReadOnly(True)
        self.agent_log.setMaximumHeight(125)
        self.agent_log.setPlaceholderText("گزارش پیشرفت مأموریت‌های Ai1 Code اینجا نمایش داده می‌شود.")
        task_layout.addWidget(self.agent_log)
        right_layout.addWidget(task_box)

        self.pages = QTabWidget()
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("از فهرست سمت راست یک فایل متنی را باز کن.")
        self.editor.textChanged.connect(self._editor_changed)
        self.pages.addTab(self.editor, "ویرایشگر")

        terminal_page = QWidget()
        terminal_layout = QVBoxLayout(terminal_page)
        terminal_layout.setContentsMargins(4, 4, 4, 4)
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setPlaceholderText(
            "ترمینال PowerShell پروژه. هر دستور پیش از اجرا تأیید می‌خواهد و با دسترسی حساب ویندوز اجرا می‌شود."
        )
        terminal_row = QHBoxLayout()
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("دستور PowerShell…")
        self.terminal_run_btn = QPushButton("اجرا با تأیید")
        terminal_row.addWidget(self.terminal_input, 1)
        terminal_row.addWidget(self.terminal_run_btn)
        terminal_layout.addWidget(self.terminal_output, 1)
        terminal_layout.addLayout(terminal_row)
        self.pages.addTab(terminal_page, "ترمینال")
        right_layout.addWidget(self.pages, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self.status = QLabel("آماده")
        self.status.setObjectName("hint")
        outer.addWidget(self.status)

        self.project_btn.clicked.connect(self.choose_project)
        self.refresh_btn.clicked.connect(self.refresh)
        self.new_file_btn.clicked.connect(self.create_file)
        self.rename_btn.clicked.connect(self.rename_file)
        self.save_btn.clicked.connect(self.save_file)
        self.files.itemDoubleClicked.connect(self._item_opened)
        self.task_btn.clicked.connect(lambda: self.start_agent(False))
        self.analyze_btn.clicked.connect(lambda: self.start_agent(True))
        self.stop_btn.clicked.connect(self.stop_agent)
        self.task_input.returnPressed.connect(lambda: self.start_agent(False))
        self.terminal_run_btn.clicked.connect(self.run_terminal)
        self.terminal_input.returnPressed.connect(self.run_terminal)
        self.refresh()

    # ------------------------------------------------------------- project
    def _set_status(self, message):
        self.status.setText(str(message or ""))
    
    def choose_project(self):
        if self._dirty and not self._confirm_discard():
            return
        if self.code.choose_project():
            self.current_file = None
            self._original_bytes = b""
            self._dirty = False
            self.editor.clear()
            self.refresh()

    def refresh(self):
        self.root = Path(self.code.root).resolve() if self.code.root and Path(self.code.root).is_dir() else None
        self.project_path.setText(str(self.root) if self.root else "")
        self.files.clear()
        self.rename_btn.setEnabled(False)
        self.new_file_btn.setEnabled(self.root is not None)
        if self.root is None:
            self._set_status("برای شروع، پوشه‌ی پروژه را انتخاب کن.")
            return

        root_item = QTreeWidgetItem([self.root.name])
        root_item.setData(0, Qt.UserRole, "")
        self.files.addTopLevelItem(root_item)
        folders = {"": root_item}
        file_count = 0
        try:
            for current, dirs, names in os.walk(self.root, topdown=True, followlinks=False):
                current_path = Path(current)
                rel_dir = current_path.relative_to(self.root).as_posix()
                if rel_dir == ".":
                    rel_dir = ""
                dirs[:] = sorted(
                    d for d in dirs
                    if d.lower() not in SKIP_DIRS
                    and not (current_path / d).is_symlink()
                    and not _is_sensitive(Path(rel_dir) / d)
                )
                parent_item = folders.get(rel_dir, root_item)
                for folder in dirs:
                    relative = (Path(rel_dir) / folder).as_posix() if rel_dir else folder
                    child = QTreeWidgetItem([folder])
                    child.setData(0, Qt.UserRole, relative)
                    parent_item.addChild(child)
                    folders[relative] = child
                for filename in sorted(names):
                    target = current_path / filename
                    relative = target.relative_to(self.root)
                    if target.is_symlink() or _is_sensitive(relative):
                        continue
                    child = QTreeWidgetItem([filename])
                    child.setData(0, Qt.UserRole, relative.as_posix())
                    parent_item.addChild(child)
                    file_count += 1
        except OSError as exc:
            self._set_status(f"خواندن فهرست پروژه ناموفق بود: {exc}")
            return
        root_item.setExpanded(True)
        self._set_status(f"پروژه آماده است · {file_count} فایل قابل مشاهده")
        self.rename_btn.setEnabled(self.current_file is not None)

    def _confirm_discard(self):
        answer = QMessageBox.question(
            self, "تغییر ذخیره‌نشده",
            "فایل فعلی تغییر کرده است. تغییرات ذخیره شوند؟",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_file()
        self._dirty = False
        return True

    def _item_opened(self, item, _column):
        if self._dirty and not self._confirm_discard():
            return
        relative = str(item.data(0, Qt.UserRole) or "")
        if not relative:
            item.setExpanded(not item.isExpanded())
            return
        target = self.root / relative
        if target.is_dir():
            item.setExpanded(not item.isExpanded())
            return
        try:
            safe = safe_project_file(self.root, target)
            raw = safe.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("فایل از سقف ۵۱۲ کیلوبایت بزرگ‌تر است.")
            text = raw.decode("utf-8-sig")
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, "باز کردن فایل", f"فایل باز نشد: {exc}")
            return
        self.current_file = safe
        self._original_bytes = raw
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._dirty = False
        self.rename_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.pages.setCurrentIndex(0)
        self._set_status(f"فایل باز شد: {safe.relative_to(self.root).as_posix()}")

    # ------------------------------------------------------------- file actions
    def _editor_changed(self):
        if self.current_file is None:
            return
        self._dirty = self.editor.toPlainText().encode("utf-8") != self._original_bytes
        self.save_btn.setEnabled(self._dirty)

    def save_file(self):
        if self.current_file is None or self.root is None:
            QMessageBox.information(self, "ذخیره فایل", "ابتدا یک فایل را باز کن.")
            return False
        try:
            target = safe_project_file(self.root, self.current_file)
            new_text = self.editor.toPlainText()
            encoded = new_text.encode("utf-8")
            if len(encoded) > MAX_FILE_BYTES:
                raise ValueError("فایل پیشنهادی از سقف ۵۱۲ کیلوبایت بیشتر است.")
            if encoded == self._original_bytes:
                self._dirty = False
                self.save_btn.setEnabled(False)
                return True
            if QMessageBox.question(
                self, "تأیید ذخیره",
                f"فایل «{target.relative_to(self.root).as_posix()}» در پوشه‌ی پروژه بازنویسی شود؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return False
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = target.with_name(target.name + f".{stamp}.ai1code.bak")
            shutil.copy2(target, backup)
            original_text = self._original_bytes.decode("utf-8-sig", errors="replace")
            if "\r\n" in original_text and "\n" not in original_text.replace("\r\n", ""):
                new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
                encoded = new_text.encode("utf-8")
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                Path(temp_name).replace(target)
            except Exception:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            self._original_bytes = target.read_bytes()
            self._dirty = False
            self.save_btn.setEnabled(False)
            self._set_status(f"ذخیره شد · پشتیبان: {backup.name}")
            return True
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "ذخیره فایل", f"ذخیره ناموفق بود: {exc}")
            return False

    def create_file(self):
        if self.root is None:
            return
        relative, ok = QInputDialog.getText(self, "فایل جدید", "مسیر نسبی داخل پروژه:")
        if not ok or not relative.strip():
            return
        relative = relative.strip().replace("\\", "/")
        parts = PurePosixPath(relative).parts
        if (relative.startswith("/") or any(part in ("", ".", "..") for part in parts)
                or len(parts) > 12):
            QMessageBox.warning(self, "فایل جدید", "مسیر باید نسبی و داخل پوشه‌ی پروژه باشد.")
            return
        rel_path = Path(*parts)
        if _is_sensitive(rel_path) or rel_path.suffix.lower() in {".exe", ".com", ".scr", ".msi", ".lnk", ".bat", ".cmd", ".ps1"}:
            QMessageBox.warning(self, "فایل جدید", "این نام یا پسوند برای ایجاد از داخل workspace مجاز نیست.")
            return
        target = self.root / rel_path
        try:
            parent = target.parent.resolve()
            parent.relative_to(self.root)
            if target.exists() or target.is_symlink():
                raise FileExistsError("فایل یا پوشه‌ای با این نام از قبل وجود دارد.")
            if QMessageBox.question(
                self, "تأیید ساخت فایل", f"فایل «{relative}» ساخته شود؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=False)
            self.refresh()
            self._open_path(target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "فایل جدید", str(exc))

    def _open_path(self, target: Path):
        relative = target.relative_to(self.root).as_posix()
        item = self._find_item(relative)
        if item is not None:
            self._item_opened(item, 0)

    def _find_item(self, relative):
        root = self.files.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            item = stack.pop()
            if str(item.data(0, Qt.UserRole) or "") == relative:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def rename_file(self):
        if self.current_file is None or self.root is None:
            return
        if self._dirty and not self._confirm_discard():
            return
        relative = self.current_file.relative_to(self.root).as_posix()
        new_name, ok = QInputDialog.getText(self, "تغییر نام فایل", "نام یا مسیر نسبی جدید:", text=relative)
        if not ok or not new_name.strip():
            return
        candidate = new_name.strip().replace("\\", "/")
        parts = PurePosixPath(candidate).parts
        if candidate.startswith("/") or any(part in ("", ".", "..") for part in parts):
            QMessageBox.warning(self, "تغییر نام", "مسیر جدید باید داخل پوشه‌ی پروژه باشد.")
            return
        rel_path = Path(*parts)
        if _is_sensitive(rel_path) or rel_path.suffix.lower() in {".exe", ".com", ".scr", ".msi", ".lnk", ".bat", ".cmd", ".ps1"}:
            QMessageBox.warning(self, "تغییر نام", "نام یا پسوند جدید مجاز نیست.")
            return
        target = self.root / rel_path
        try:
            safe_project_file(self.root, self.current_file)
            parent = target.parent.resolve()
            parent.relative_to(self.root)
            if target.exists() or target.is_symlink():
                raise FileExistsError("مقصد از قبل وجود دارد.")
            if QMessageBox.question(
                self, "تأیید تغییر نام", f"«{relative}» به «{candidate}» تغییر کند؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            parent.mkdir(parents=True, exist_ok=True)
            self.current_file.replace(target)
            self.current_file = target
            self._original_bytes = target.read_bytes()
            self._dirty = False
            self.refresh()
            self._set_status(f"نام فایل تغییر کرد: {candidate}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "تغییر نام", str(exc))

    # ------------------------------------------------------------- agent
    def start_agent(self, readonly=False):
        goal = self.task_input.text().strip()
        if not goal:
            return
        if self.root is None:
            QMessageBox.information(self, "Ai1 Code", "ابتدا پوشه‌ی پروژه را انتخاب کن.")
            return
        if self._dirty and not self._confirm_discard():
            return
        if self.window.busy or (self.code.job is not None and self.code.job.isRunning()):
            QMessageBox.information(self, "Ai1 Code", "یک پاسخ یا مأموریت دیگر هنوز در حال اجراست.")
            return
        session = self.window.sessions.get("kira")
        if session is None:
            QMessageBox.warning(self, "Ai1 Code", "گفتگوی Kira در دسترس نیست.")
            return
        self.task_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._append_agent("درخواست به Code Agent ارسال شد.")
        try:
            with self.window._as(session):
                self.code.session = session
                self.code.start_auto(goal, readonly=readonly, history=self.code._history())
            if self.code.job is None or not self.code.job.isRunning():
                self._agent_finished()
        except Exception as exc:  # noqa: BLE001
            self._append_agent(f"خطا: {exc}")
            self._agent_finished()
            return
        self.task_input.clear()

    def stop_agent(self):
        session = self.window.sessions.get("kira")
        if session is not None:
            self.code.stop(session)
        self._set_status("درخواست توقف ارسال شد.")

    def _append_agent(self, text):
        self.agent_log.appendPlainText(str(text or ""))
        bar = self.agent_log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_agent_event(self, text):
        self._append_agent(text)

    def show_agent_result(self, result):
        if isinstance(result, dict):
            self._append_agent(str(result.get("summary") or "مأموریت تمام شد."))
            if result.get("zip"):
                self._append_agent("خروجی ZIP: " + str(result.get("zip")))
        self._agent_finished()

    def _agent_finished(self):
        self.task_btn.setEnabled(True)
        self.analyze_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ------------------------------------------------------------- terminal
    def run_terminal(self):
        command = self.terminal_input.text().strip()
        if not command:
            return
        if self.root is None:
            QMessageBox.information(self, "ترمینال", "ابتدا پوشه‌ی پروژه را انتخاب کن.")
            return
        if self.window.busy or (self.code.proc is not None and self.code.proc.state() != QProcess.NotRunning):
            QMessageBox.information(self, "ترمینال", "یک پاسخ یا دستور دیگر هنوز در حال اجراست.")
            return
        self.pages.setCurrentIndex(1)
        self.terminal_output.appendPlainText(f"\nPS {self.root}> {command}")
        self.terminal_input.clear()
        try:
            session = self.window.sessions.get("kira")
            if session is None:
                raise RuntimeError("گفتگوی Kira در دسترس نیست.")
            with self.window._as(session):
                self.code.session = session
                self.code.run_command(command)
        except Exception as exc:  # noqa: BLE001
            self.terminal_output.appendPlainText(f"خطا: {exc}")

    def append_terminal(self, command, output, exit_code):
        self.terminal_output.appendPlainText(str(output or "(بدون خروجی)"))
        self.terminal_output.appendPlainText(f"کد خروج: {exit_code}")
        self._set_status(f"ترمینال تمام شد · exit {exit_code}")
