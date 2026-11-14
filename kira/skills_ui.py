"""Compact UI for the shared Agent Skills library."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QListWidget, QListWidgetItem, QTextEdit, QCheckBox,
    QFileDialog, QMessageBox, QGroupBox, QFormLayout,
)


class _SkillsWorker(QThread):
    completed = Signal(object)

    def __init__(self, function, *args):
        super().__init__()
        self.function = function
        self.args = args

    def run(self):
        try:
            self.completed.emit((True, self.function(*self.args)))
        except Exception as exc:  # noqa: BLE001
            self.completed.emit((False, f"{type(exc).__name__}: {exc}"))


class SkillsPage(QWidget):
    """Search, preview, install and manage shared skills without executing their scripts."""

    def __init__(self, manager, settings_getter, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.settings_getter = settings_getter
        self._worker = None
        self._preview = None
        self._preview_item = None
        self._job_kind = ""
        self._job_target = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        intro = QLabel(
            "کتابخانه‌ی مهارت‌ها بین Kira، Ren و Mika مشترک است. هر مهارت فقط یک‌بار نصب می‌شود؛ "
            "فعال‌بودن آن برای هر شخصیت جداگانه تنظیم می‌شود. فایل‌های اجرایی مهارت به‌صورت خودکار اجرا نمی‌شوند."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)

        search_box = QGroupBox("جست‌وجو و دریافت مهارت")
        search_layout = QVBoxLayout(search_box)
        controls = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("Skills.sh", "skills.sh")
        self.source.addItem("GitHub", "github")
        self.query = QLineEdit()
        self.query.setPlaceholderText("نام مهارت یا موضوع موردنظر…")
        self.search_btn = QPushButton("جست‌وجو")
        self.preview_btn = QPushButton("پیش‌نمایش")
        self.local_btn = QPushButton("نصب از فایل محلی")
        controls.addWidget(self.source)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.search_btn)
        search_layout.addLayout(controls)

        results_row = QHBoxLayout()
        self.results = QListWidget()
        self.results.setMinimumHeight(130)
        self.results.setMaximumHeight(210)
        results_side = QVBoxLayout()
        results_side.addWidget(self.preview_btn)
        results_side.addWidget(self.local_btn)
        results_side.addStretch(1)
        results_row.addWidget(self.results, 1)
        results_row.addLayout(results_side)
        search_layout.addLayout(results_row)
        root.addWidget(search_box)

        preview_box = QGroupBox("مشخصات و بررسی امنیتی")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(105)
        self.preview_text.setMaximumHeight(190)
        self.preview_text.setPlaceholderText("یک نتیجه را انتخاب و پیش‌نمایش کن؛ توضیحات، منبع، مجوز و هشدارهای امنیتی اینجا نمایش داده می‌شوند.")
        preview_layout.addWidget(self.preview_text)
        install_row = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem("فقط برای شخصیت انتخاب‌شده", "character")
        self.scope.addItem("سراسری (Global)", "global")
        self.character = QComboBox()
        self.install_btn = QPushButton("نصب مهارت")
        self.install_btn.setEnabled(False)
        install_row.addWidget(QLabel("دامنه:"))
        install_row.addWidget(self.scope)
        install_row.addWidget(QLabel("شخصیت:"))
        install_row.addWidget(self.character, 1)
        install_row.addWidget(self.install_btn)
        preview_layout.addLayout(install_row)
        root.addWidget(preview_box)

        installed_box = QGroupBox("کتابخانه‌ی نصب‌شده")
        installed_layout = QVBoxLayout(installed_box)
        installed_row = QHBoxLayout()
        self.installed = QListWidget()
        self.installed.setMinimumHeight(100)
        self.installed.setMaximumHeight(180)
        installed_controls = QVBoxLayout()
        self.enabled = QCheckBox("فعال برای شخصیت انتخاب‌شده")
        self.remove_btn = QPushButton("حذف از کتابخانه")
        self.remove_btn.setEnabled(False)
        installed_controls.addWidget(self.enabled)
        installed_controls.addWidget(self.remove_btn)
        installed_controls.addStretch(1)
        installed_row.addWidget(self.installed, 1)
        installed_row.addLayout(installed_controls)
        installed_layout.addLayout(installed_row)
        self.installed_detail = QLabel("")
        self.installed_detail.setWordWrap(True)
        self.installed_detail.setObjectName("hint")
        installed_layout.addWidget(self.installed_detail)
        root.addWidget(installed_box, 1)

        self.search_btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.preview_btn.clicked.connect(self.preview_selected)
        self.local_btn.clicked.connect(self.import_local)
        self.install_btn.clicked.connect(self.install_preview)
        self.results.currentItemChanged.connect(self._result_changed)
        self.character.currentIndexChanged.connect(self.refresh_installed)
        self.installed.currentItemChanged.connect(self._installed_changed)
        self.enabled.toggled.connect(self._toggle_enabled)
        self.remove_btn.clicked.connect(self.remove_selected)
        self._refresh_characters()
        self.refresh_installed()

    def set_character(self, character_id):
        index = self.character.findData(str(character_id or "kira"))
        if index >= 0 and index != self.character.currentIndex():
            self.character.setCurrentIndex(index)

    def _refresh_characters(self):
        current = self.character.currentData() if self.character.count() else ""
        settings = self.settings_getter() or {}
        try:
            from .personas import all_profiles
            profiles = all_profiles(settings)
        except Exception:
            profiles = {"kira": {"id": "kira", "name": "Kira"}}
        self.character.blockSignals(True)
        self.character.clear()
        for cid, profile in profiles.items():
            self.character.addItem(str(profile.get("name") or cid), str(cid))
        index = self.character.findData(current or "kira")
        self.character.setCurrentIndex(index if index >= 0 else 0)
        self.character.blockSignals(False)

    def _start_job(self, kind, function, *args, target=None):
        if self._worker is not None and self._worker.isRunning():
            return
        self._job_kind = kind
        self._job_target = target
        self.search_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.local_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self._worker = _SkillsWorker(function, *args)
        self._worker.completed.connect(self._job_done)
        self._worker.start()

    def search(self):
        self.results.clear()
        self.preview_text.clear()
        self._preview = None
        self._preview_item = None
        self.install_btn.setEnabled(False)
        self._start_job("search", self.manager.search, self.source.currentData(), self.query.text())

    def _result_changed(self, current, _previous):
        self._preview = None
        self._preview_item = current.data(Qt.UserRole) if current is not None else None
        self.preview_text.clear()
        self.install_btn.setEnabled(False)

    def preview_selected(self):
        item = self._preview_item
        if not isinstance(item, dict):
            QMessageBox.information(self, "Skills", "ابتدا یک نتیجه را انتخاب کن.")
            return
        self._start_job("preview", self.manager.preview_remote, item, target=item)

    def import_local(self):
        path = QFileDialog.getExistingDirectory(self, "انتخاب پوشه‌ی Skill")
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل Skill", "", "Skill archives (*.zip *.skill);;All files (*)")
        if not path:
            return
        self._preview = None
        self._start_job("local_preview", self.manager.preview_local, path)

    def _job_done(self, result):
        self.search_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.local_btn.setEnabled(True)
        ok, value = result
        kind = self._job_kind
        self._job_kind = ""
        if not ok:
            QMessageBox.warning(self, "Skills", str(value))
            return
        if kind == "search":
            self.results.clear()
            for record in value:
                name = str(record.get("name") or "نامشخص")
                source = str(record.get("source") or record.get("source_type") or "")
                installs = int(record.get("installs") or 0)
                label = f"{name}  ·  {source}" + (f"  ·  {installs:,} نصب" if installs else "")
                row = QListWidgetItem(label)
                row.setData(Qt.UserRole, record)
                self.results.addItem(row)
            if not value:
                self.preview_text.setPlainText("نتیجه‌ای پیدا نشد. منبع دیگر را امتحان کن.")
        elif kind in ("preview", "local_preview"):
            self._show_preview(value)

    def _show_preview(self, preview):
        self._preview = preview
        self.install_btn.setEnabled(True)
        findings = preview.get("security_findings") or []
        risk = "، ".join(findings) if findings else "مورد مشکوک شناخته‌شده‌ای در بررسی ایستا پیدا نشد."
        self.preview_text.setPlainText(
            f"نام: {preview.get('name')}\n"
            f"توضیحات: {preview.get('description')}\n"
            f"منبع: {preview.get('source')}\n"
            f"مجوز: {preview.get('license') or 'مشخص نشده'}\n"
            f"سازگاری: {preview.get('compatibility') or 'ذکر نشده'}\n"
            f"فایل‌ها: {preview.get('file_count')} · حجم: {preview.get('bytes')} بایت\n"
            f"بررسی امنیتی: {risk}\n\n"
            f"{preview.get('body') or ''}\n\n"
            "توجه: بررسی امنیتی ایستا تضمین امنیت نیست. اسکریپت‌ها اجرا نمی‌شوند و Skill اجازه‌ی جدیدی به ابزارهای Kira نمی‌دهد."
        )

    def install_preview(self):
        if not self._preview:
            return
        preview = self._preview
        scope = self.scope.currentData()
        cid = self.character.currentData() or "kira"
        scope_label = "سراسری برای همه‌ی شخصیت‌ها" if scope == "global" else f"ویژه‌ی {self.character.currentText()}"
        answer = QMessageBox.question(
            self, "تأیید نصب مهارت",
            f"مهارت «{preview.get('name')}» با مجوز «{preview.get('license') or 'مشخص نشده'}» نصب شود؟\n"
            f"دامنه: {scope_label}\nمنبع: {preview.get('source')}\n\n"
            "فایل‌های همراه اجرا نمی‌شوند. بررسی ایستا نیز تضمین امنیت کامل نیست.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            record = self.manager.install_preview(preview, scope, cid)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "خطای نصب Skill", str(exc))
            return
        self._preview = None
        self.install_btn.setEnabled(False)
        self.preview_text.append("\nنصب شد: " + record["name"])
        self.refresh_installed()

    def refresh_installed(self, *_):
        self._refresh_characters()
        self.installed.blockSignals(True)
        selected = self.installed.currentItem().data(Qt.UserRole) if self.installed.currentItem() else None
        self.installed.clear()
        cid = self.character.currentData() or "kira"
        for skill in self.manager.list_skills():
            active = self.manager.is_enabled(skill, cid)
            scope = "Global" if skill.get("scope") == "global" else "Character"
            label = "●" if active else "○"
            row = QListWidgetItem(f"{label}  {skill['name']}  ·  {scope}")
            row.setData(Qt.UserRole, skill["name"])
            self.installed.addItem(row)
            if skill["name"] == selected:
                self.installed.setCurrentItem(row)
        self.installed.blockSignals(False)
        self._installed_changed(self.installed.currentItem(), None)

    def _installed_changed(self, current, _previous):
        name = current.data(Qt.UserRole) if current is not None else ""
        detail = self.manager.get_skill(name) if name else None
        self.remove_btn.setEnabled(bool(detail))
        self.enabled.blockSignals(True)
        self.enabled.setEnabled(bool(detail) and (detail.get("scope") == "global" or
                                                   (self.character.currentData() or "kira") in detail.get("characters", [])))
        self.enabled.setChecked(bool(detail) and self.manager.is_enabled(detail, self.character.currentData() or "kira"))
        self.enabled.blockSignals(False)
        if detail:
            self.installed_detail.setText(
                f"{detail.get('description', '')}  |  منبع: {detail.get('source', '')}  |  مجوز: {detail.get('license', 'مشخص نشده')}"
            )
        else:
            self.installed_detail.setText("")

    def _toggle_enabled(self, value):
        current = self.installed.currentItem()
        if current is None:
            return
        try:
            self.manager.set_enabled(current.data(Qt.UserRole), self.character.currentData() or "kira", value)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Skills", str(exc))
        self.refresh_installed()

    def remove_selected(self):
        current = self.installed.currentItem()
        if current is None:
            return
        name = current.data(Qt.UserRole)
        answer = QMessageBox.question(
            self, "حذف Skill",
            f"«{name}» از کتابخانه‌ی مشترک حذف شود؟ برای همه‌ی شخصیت‌ها حذف خواهد شد.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.manager.remove(name)
            self.refresh_installed()
