"""Independent Help/About page for project links and user documentation."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class HelpPage(QScrollArea):
    """Self-contained Help/About page with no MainWindow implementation dependency."""

    def __init__(
        self,
        translate: Callable[[str], str],
        *,
        app_name: str,
        version: str,
        releases_url: str,
        project_url: str,
    ) -> None:
        super().__init__()
        self._translate = translate
        self._app_name = str(app_name)
        self._version = str(version)
        self._releases_url = str(releases_url)
        self._project_url = str(project_url)

        self.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.update_box = QGroupBox()
        update_form = QFormLayout(self.update_box)
        update_form.setLabelAlignment(Qt.AlignLeading)
        update_form.setHorizontalSpacing(8)
        update_form.setVerticalSpacing(5)

        self.version_label = QLabel(f"{self._app_name} · {self._version}")
        self.version_label.setObjectName("title")
        update_form.addRow(self.version_label)

        self.description = QLabel()
        self.description.setWordWrap(True)
        update_form.addRow(self.description)

        self.latest_btn = QPushButton()
        self.repo_btn = QPushButton()
        self.guide_btn = QPushButton()
        self.troubleshoot_btn = QPushButton()
        self.changes_btn = QPushButton()
        self.data_btn = QPushButton()

        self.latest_btn.clicked.connect(lambda: self._open(self._releases_url))
        self.repo_btn.clicked.connect(lambda: self._open(self._project_url))
        self.guide_btn.clicked.connect(
            lambda: self._open(self._project_url + "/blob/main/docs/USAGE_FA.md")
        )
        self.troubleshoot_btn.clicked.connect(
            lambda: self._open(self._project_url + "/blob/main/docs/WINDOWS11_CHECKLIST_FA.md")
        )
        self.changes_btn.clicked.connect(lambda: self._open(self._project_url + "/commits/main"))
        self.data_btn.clicked.connect(
            lambda: self._open(self._project_url + "/blob/main/docs/CHARACTER_PROFILES_FA.md")
        )
        for button in (
            self.latest_btn,
            self.repo_btn,
            self.guide_btn,
            self.troubleshoot_btn,
            self.changes_btn,
            self.data_btn,
        ):
            update_form.addRow(button)

        self.about_box = QGroupBox()
        about_form = QFormLayout(self.about_box)
        about_form.setLabelAlignment(Qt.AlignLeading)
        self.about_label = QLabel()
        self.about_label.setWordWrap(True)
        about_form.addRow(self.about_label)

        layout.addWidget(self.update_box)
        layout.addWidget(self.about_box)
        layout.addStretch(1)
        self.setWidget(host)
        self.retranslate()

    @staticmethod
    def _open(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def retranslate(self) -> None:
        self.update_box.setTitle(self._translate("g_help_updates"))
        self.description.setText(self._translate("help_description"))
        self.latest_btn.setText(self._translate("help_latest"))
        self.repo_btn.setText(self._translate("help_repository"))
        self.guide_btn.setText(self._translate("help_guide"))
        self.troubleshoot_btn.setText(self._translate("help_troubleshooting"))
        self.changes_btn.setText(self._translate("help_changes"))
        self.data_btn.setText(self._translate("help_data"))
        self.about_box.setTitle(self._translate("g_help_about"))
        self.about_label.setText(self._translate("help_about_text"))
