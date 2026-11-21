"""Qt presentation for the application-owned shared Skills use cases."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from kira.ui.pages._all_pages_fluid_finalizers import finalize_skills_page

from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class SkillsPage(QScrollArea):
    install_zip_requested = Signal()
    install_folder_requested = Signal()
    enable_changed = Signal(str, bool, object)
    uninstall_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("کتابخانه مشترک Skillها")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        description = QLabel(
            "هر Skill یک‌بار نصب می‌شود و می‌توانی آن را برای همه شخصیت‌ها یا فقط "
            "Kira، Ren و Mika فعال کنی. محتوای Skill فقط دستور متنی است و کد اجرایی اجرا نمی‌شود."
        )
        description.setWordWrap(True)
        description.setObjectName("hint")
        layout.addWidget(description)

        actions = QHBoxLayout()
        self.install_zip_btn = QPushButton("نصب فایل ZIP")
        self.install_zip_btn.clicked.connect(self.install_zip_requested.emit)
        self.install_folder_btn = QPushButton("نصب پوشه")
        self.install_folder_btn.clicked.connect(self.install_folder_requested.emit)
        actions.addWidget(self.install_zip_btn)
        actions.addWidget(self.install_folder_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self.status = QLabel("هنوز Skillای نصب نشده است.")
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        layout.addWidget(self.status)
        self.setWidget(host)

        finalize_skills_page(self)

    def set_status(self, message: str, error: bool = False):
        self.status.setText(str(message))
        self.status.setProperty("error", bool(error))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_skills(self, manifests, profiles, application_service):
        ordered = []
        for key in ("kira", "ren", "mika"):
            if key in profiles:
                ordered.append((key, profiles[key]))
        ordered.extend(
            (key, value) for key, value in profiles.items()
            if key not in {"kira", "ren", "mika"}
        )
        character_columns = [
            (str(cid), str(profile.get("name_fa") or profile.get("name") or cid))
            for cid, profile in ordered
        ]
        headers = ["Skill", "توضیحات", "سراسری"]
        headers.extend(name for _cid, name in character_columns)
        headers.append("حذف")
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(manifests))

        for row, manifest in enumerate(manifests):
            name = QTableWidgetItem(f"{manifest.name} · v{manifest.version}")
            name.setToolTip(manifest.skill_id)
            self.table.setItem(row, 0, name)
            description = QTableWidgetItem(manifest.description or "—")
            description.setToolTip(manifest.description or "")
            self.table.setItem(row, 1, description)

            global_box = QCheckBox()
            global_box.setChecked(application_service.is_globally_enabled(manifest.skill_id))
            global_box.setToolTip("فعال‌سازی برای همه شخصیت‌ها")
            global_box.stateChanged.connect(
                lambda state, sid=manifest.skill_id: self.enable_changed.emit(
                    sid, state == Qt.Checked, None
                )
            )
            self.table.setCellWidget(row, 2, self._center(global_box))

            for offset, (cid, _label) in enumerate(character_columns, start=3):
                check = QCheckBox()
                check.setChecked(application_service.is_enabled(manifest.skill_id, cid))
                check.setToolTip(f"فعال‌سازی برای {cid}")
                check.stateChanged.connect(
                    lambda state, sid=manifest.skill_id, character=cid:
                    self.enable_changed.emit(sid, state == Qt.Checked, character)
                )
                self.table.setCellWidget(row, offset, self._center(check))

            remove = QPushButton("حذف")
            remove.setObjectName("danger")
            remove.clicked.connect(
                lambda _checked=False, sid=manifest.skill_id:
                self.uninstall_requested.emit(sid)
            )
            self.table.setCellWidget(row, len(headers) - 1, self._center(remove))

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(max(180, min(520, 46 * len(manifests) + 42)))
        if not manifests:
            self.set_status("هنوز Skillای نصب نشده است. فایل ZIP یا پوشه یک Skill را نصب کن.")
        else:
            self.set_status(f"{len(manifests)} Skill در کتابخانه مشترک نصب شده است.")

    @staticmethod
    def _center(widget):
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(widget)
        return wrapper
