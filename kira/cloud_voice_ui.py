"""The "Cloud Voice" section of the settings: API keys per provider, detected capabilities, STT / TTS priority and failover.

Everything is written to the Cloud Voice store immediately (kira/cloud_voice.py -> cloud_voice.json in Kira's data folder)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget, QAbstractItemView)

from . import cloud_voice as cv


class _Job(QThread):
    """Runs one blocking function (validation = a network call) off the GUI thread."""
    finished_with = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.finished_with.emit(self.fn())
        except Exception as exc:                          # noqa: BLE001
            self.finished_with.emit({"status": "error", "error": f"{type(exc).__name__}: {exc}", "detected": {}})


class KeyDialog(QDialog):
    def __init__(self, t, title, label="", editing=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.label = QLineEdit(label)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText(t("cv_f_keep") if editing else "")
        self.show_chk = QCheckBox(t("cv_show"))
        self.show_chk.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        form.addRow(t("cv_f_label"), self.label)
        form.addRow(t("cv_f_key"), self.key)
        form.addRow(self.show_chk)
        self.editing = editing
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _ok(self):
        if self.key.text().strip() or self.editing:
            self.accept()


class ProviderBox(QGroupBox):
    """One provider: its keys (table), its detected models and what it can do."""

    def __init__(self, page, provider):
        super().__init__()
        self.page, self.provider = page, provider
        self.store = page.service.store
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.caps = QLabel()
        self.caps.setWordWrap(True)
        self.add_btn = QPushButton()
        self.add_btn.clicked.connect(self.add_key)
        self.link = QLabel(f'<a href="{cv.KEY_URLS[provider]}">…</a>')
        self.link.setOpenExternalLinks(True)
        top.addWidget(self.caps, 1)
        top.addWidget(self.link)
        top.addWidget(self.add_btn)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(170)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._item_changed)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.btn_edit, self.btn_del, self.btn_val, self.btn_up, self.btn_dn = (QPushButton() for _ in range(5))
        self.btn_up.setText("▲")
        self.btn_dn.setText("▼")
        self.btn_edit.clicked.connect(self.edit_key)
        self.btn_del.clicked.connect(self.delete_key)
        self.btn_val.clicked.connect(self.validate_selected)
        self.btn_up.clicked.connect(lambda: self.move(-1))
        self.btn_dn.clicked.connect(lambda: self.move(1))
        for b in (self.btn_edit, self.btn_del, self.btn_val, self.btn_up, self.btn_dn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.models = QLabel()
        self.models.setWordWrap(True)
        self.models.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.models)
        self._busy = False

    # ---- text / refresh ----
    def retranslate(self):
        t = self.page.t
        self.setTitle(t("cv_g_keys", name=cv.LABELS[self.provider]))
        self.add_btn.setText(t("cv_add_key"))
        self.link.setText(f'<a href="{cv.KEY_URLS[self.provider]}">{t("cv_get_key")}</a>')
        for b, key in ((self.btn_edit, "cv_edit"), (self.btn_del, "cv_delete"), (self.btn_val, "cv_validate")):
            b.setText(t(key))
        self.btn_up.setToolTip(t("cv_up"))
        self.btn_dn.setToolTip(t("cv_down"))
        self.table.setHorizontalHeaderLabels([t(k) for k in ("cv_col_on", "cv_col_label", "cv_col_key", "cv_col_status", "cv_col_stt", "cv_col_tts")])
        self.refresh()

    def status_text(self, rec):
        t = self.page.t
        if rec.get("cooldown_until", 0) > time.time():
            return t("cv_st_cool", t=time.strftime("%H:%M", time.localtime(rec["cooldown_until"])))
        return t("cv_st_" + (rec.get("status") if rec.get("status") in ("valid", "invalid", "quota", "error") else "unchecked"))

    def refresh(self):
        t, store = self.page.t, self.store
        selected = self.selected_id()
        self.table.blockSignals(True)
        keys = store.keys(self.provider)
        self.table.setRowCount(len(keys))
        for r, rec in enumerate(keys):
            det = rec.get("detected") or {}
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            on.setCheckState(Qt.Checked if rec.get("enabled") else Qt.Unchecked)
            on.setData(Qt.UserRole, rec["id"])
            cells = [on, QTableWidgetItem(rec.get("label", "")), QTableWidgetItem(cv.mask(rec.get("key", ""))),
                     QTableWidgetItem(self.status_text(rec)),
                     QTableWidgetItem("✓" if det.get("stt") else "✗"), QTableWidgetItem("✓" if det.get("tts") else "✗")]
            cells[3].setToolTip(rec.get("error", ""))
            for c, item in enumerate(cells):
                if c:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(r, c, item)
            if rec["id"] == selected:
                self.table.selectRow(r)
        self.table.blockSignals(False)
        stt_ok, tts_ok = store.capable(self.provider, "stt"), store.capable(self.provider, "tts")
        self.caps.setText(t("cv_caps", stt=t("cv_yes" if stt_ok else "cv_no"), tts=t("cv_yes" if tts_ok else "cv_no")) if keys else t("cv_note_nokeys"))
        lines = []
        for kind, title in (("stt", "cv_models_stt"), ("tts", "cv_models_tts")):
            entries = store.models(self.provider, kind)
            names = ", ".join(e["id"] + (f" ({t('cv_keys_n', n=len(e['keys']))})" if len(e["keys"]) > 1 else "") for e in entries) or t("cv_none")
            catalog = any((k.get("detected") or {}).get("stt_source") == "catalog" for k in keys) and kind == "stt" and entries
            lines.append(f"{t(title)} {names}" + (f" {t('cv_catalog')}" if catalog else ""))
        self.models.setText("\n".join(lines))

    def selected_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        item = self.table.item(rows[0].row(), 0) if rows else None
        return item.data(Qt.UserRole) if item else None

    # ---- actions ----
    def _item_changed(self, item):
        if item.column() == 0:
            self.store.update_key(self.provider, item.data(Qt.UserRole), enabled=item.checkState() == Qt.Checked)
            self.page.refresh()

    def _need_selection(self):
        kid = self.selected_id()
        if not kid:
            QMessageBox.information(self, self.title(), self.page.t("cv_select_key"))
        return kid

    def _validate_async(self, key_text, done):
        if self._busy:
            return
        self._busy = True
        self.add_btn.setEnabled(False)
        self.btn_val.setEnabled(False)
        self.page.status.setText(self.page.t("cv_validating"))
        job = _Job(lambda: cv.validate(self.provider, key_text), self)

        def finish(result):
            self._busy = False
            self.add_btn.setEnabled(True)
            self.btn_val.setEnabled(True)
            self.page.status.setText("")
            done(result)
            self.page.refresh()
        job.finished_with.connect(finish)
        job.finished.connect(job.deleteLater)
        self._job = job
        job.start()

    def add_key(self):
        dlg = KeyDialog(self.page.t, self.page.t("cv_dlg_add", name=cv.LABELS[self.provider]), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        key, label = dlg.key.text().strip(), dlg.label.text().strip()

        def done(result):
            if result["status"] != "valid":
                reply = QMessageBox.question(self, self.title(), self.page.t("cv_add_bad", e=result.get("error", "")))
                if reply != QMessageBox.Yes:
                    return
                result = {**result, "status": result["status"] if result["status"] != "error" else "unchecked"}
            self.store.add_key(self.provider, key, label, result)
        self._validate_async(key, done)

    def edit_key(self):
        kid = self._need_selection()
        rec = self.store.find_key(self.provider, kid) if kid else None
        if not rec:
            return
        dlg = KeyDialog(self.page.t, self.page.t("cv_dlg_edit", name=cv.LABELS[self.provider]), rec.get("label", ""), editing=True, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        new_key = dlg.key.text().strip()
        self.store.update_key(self.provider, kid, label=dlg.label.text().strip() or rec["label"], **({"key": new_key} if new_key else {}))
        if new_key:
            self.validate_selected(kid)
        self.page.refresh()

    def delete_key(self):
        kid = self._need_selection()
        rec = self.store.find_key(self.provider, kid) if kid else None
        if rec and QMessageBox.question(self, self.title(), self.page.t("cv_del_q", label=rec["label"])) == QMessageBox.Yes:
            self.store.delete_key(self.provider, kid)
            self.page.refresh()

    def move(self, delta):
        kid = self.selected_id()
        if kid:
            self.store.move_key(self.provider, kid, delta)
            self.refresh()

    def validate_selected(self, kid=None):
        kid = kid if isinstance(kid, str) else self._need_selection()
        rec = self.store.find_key(self.provider, kid) if kid else None
        if rec:
            self._validate_async(rec["key"], lambda result: self.store.apply_validation(self.provider, kid, result))


class PriorityGroup(QGroupBox):
    """Independent order / switches / model (and voices for TTS) for STT or TTS, ending with the local engine."""

    def __init__(self, page, kind):
        super().__init__()
        self.page, self.kind = page, kind
        self.store = page.service.store
        self.lay = QVBoxLayout(self)
        self.use = QCheckBox()
        self.use.setChecked(bool(self.store.data[kind]["use_cloud"]))
        self.use.toggled.connect(lambda on: self.store.set_use_cloud(kind, on))
        self.lay.addWidget(self.use)
        self.grid_host = QFrame()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(self.grid_host)
        self.local = QLabel()
        self.local.setWordWrap(True)
        self.lay.addWidget(self.local)
        if kind == "tts":
            self.note = QLabel()
            self.note.setWordWrap(True)
            self.lay.addWidget(self.note)
            self.test_btn = QPushButton()
            self.test_btn.clicked.connect(page.on_test_tts)
            row = QHBoxLayout()
            row.addWidget(self.test_btn)
            row.addStretch(1)
            self.lay.addLayout(row)

    def retranslate(self):
        t = self.page.t
        self.setTitle(t("cv_g_" + self.kind))
        self.use.setText(t("cv_use_" + self.kind))
        self.local.setText(t("cv_local_last", local=t("cv_local_" + self.kind)))
        if self.kind == "tts":
            self.note.setText(t("cv_tts_note"))
            self.test_btn.setText(t("cv_test_tts"))
        self.refresh()

    def refresh(self):
        t, store, kind = self.page.t, self.store, self.kind
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        order = store.data[kind]["order"]
        for r, provider in enumerate(order):
            ok = store.capable(provider, kind)
            chk = QCheckBox(cv.LABELS[provider])
            chk.setChecked(bool(store.data[kind]["enabled"].get(provider, True)) and ok)
            chk.setEnabled(ok)
            chk.setToolTip("" if ok else t("cv_unsupported", why=store.reason_unsupported(provider, kind)))
            chk.toggled.connect(lambda on, p=provider: store.set_option(kind, "enabled", p, bool(on)))
            self.grid.addWidget(chk, r * 2, 0)
            combo = QComboBox()
            combo.setEnabled(ok)
            combo.setMinimumWidth(220)
            chosen = store.data[kind]["model"].get(provider) or ""
            for e in store.models(provider, kind):
                combo.addItem(e["id"] + (f"  ({t('cv_keys_n', n=len(e['keys']))})" if len(e["keys"]) > 1 else ""), e["id"])
            i = combo.findData(chosen)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.currentIndexChanged.connect(lambda _i, p=provider, c=combo: c.currentData() and store.set_option(kind, "model", p, c.currentData()))
            self.grid.addWidget(combo, r * 2, 1)
            up, dn = QToolButton(), QToolButton()
            up.setText("▲")
            dn.setText("▼")
            up.setToolTip(t("cv_up"))
            dn.setToolTip(t("cv_down"))
            up.setEnabled(r > 0)
            dn.setEnabled(r < len(order) - 1)
            up.clicked.connect(lambda _=False, p=provider: (store.move_provider(kind, p, -1), self.refresh()))
            dn.clicked.connect(lambda _=False, p=provider: (store.move_provider(kind, p, 1), self.refresh()))
            self.grid.addWidget(up, r * 2, 2)
            self.grid.addWidget(dn, r * 2, 3)
            if kind == "tts" and ok:
                vrow = QHBoxLayout()
                voices = store.voices(provider)
                for lang, key in (("fa", "cv_voice_fa"), ("en", "cv_voice_en"), ("ja", "cv_voice_ja")):
                    vc = QComboBox()
                    vc.setEditable(True)                          # any voice name / id can be typed
                    vc.setMinimumWidth(110)
                    vc.setToolTip(t(key))
                    for v in voices:
                        vc.addItem(v["name"], v["id"])
                    current = store.data["tts"]["voice"][provider].get(lang, "")
                    j = vc.findData(current)
                    if j >= 0:
                        vc.setCurrentIndex(j)
                    else:
                        vc.setEditText(current)
                    vc.lineEdit().setPlaceholderText(t(key))
                    vc.activated.connect(lambda _i, p=provider, l=lang, c=vc: store.set_voice(p, l, c.currentData() or c.currentText().strip()))
                    vc.lineEdit().editingFinished.connect(
                        lambda p=provider, l=lang, c=vc: store.set_voice(p, l, (c.currentData() if c.findText(c.currentText()) >= 0 else None) or c.currentText().strip()))
                    vrow.addWidget(vc)
                holder = QWidget()
                holder.setLayout(vrow)
                vrow.setContentsMargins(24, 0, 0, 6)
                self.grid.addWidget(holder, r * 2 + 1, 0, 1, 4)
        self.use.blockSignals(True)
        self.use.setChecked(bool(store.data[kind]["use_cloud"]))
        self.use.blockSignals(False)


class CloudVoicePage(QScrollArea):
    def __init__(self, service, t, test_tts=None, data_path=""):
        super().__init__()
        self.service, self.t, self._test_tts, self.data_path = service, t, test_tts, data_path
        self.setWidgetResizable(True)
        host = QWidget()
        self.lay = QVBoxLayout(host)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.stored = QLabel()
        self.stored.setWordWrap(True)
        self.stored.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status = QLabel()
        self.refresh_all_btn = QPushButton()
        self.refresh_all_btn.clicked.connect(self.validate_all)
        self.lay.addWidget(self.intro)
        self.lay.addWidget(self.stored)
        row = QHBoxLayout()
        row.addWidget(self.refresh_all_btn)
        row.addWidget(self.status, 1)
        self.lay.addLayout(row)
        self.stt = PriorityGroup(self, "stt")
        self.tts = PriorityGroup(self, "tts")
        self.lay.addWidget(self.stt)
        self.lay.addWidget(self.tts)
        self.boxes = [ProviderBox(self, p) for p in cv.PROVIDERS]
        for b in self.boxes:
            self.lay.addWidget(b)
        self.lay.addStretch(1)
        self.setWidget(host)
        self.retranslate(t)

    def retranslate(self, t=None):
        self.t = t or self.t
        self.intro.setText(self.t("cv_intro"))
        self.stored.setText(self.t("cv_stored", path=self.data_path))
        self.refresh_all_btn.setText(self.t("cv_refresh"))
        for w in (self.stt, self.tts, *self.boxes):
            w.retranslate()

    def refresh(self):
        for w in (self.stt, self.tts, *self.boxes):
            w.refresh()

    def on_test_tts(self):
        if self._test_tts:
            self._test_tts()

    def validate_all(self):
        """Validate every key one after another (off the GUI thread) and refresh the detected models."""
        todo = [(p, k["id"], k["key"]) for p in cv.PROVIDERS for k in self.service.store.keys(p) if k.get("key")]
        if not todo:
            return
        self.refresh_all_btn.setEnabled(False)
        self.status.setText(self.t("cv_validating"))

        def work():
            return [(p, kid, cv.validate(p, key)) for p, kid, key in todo]
        job = _Job(work, self)

        def finish(results):
            for p, kid, res in (results if isinstance(results, list) else []):
                self.service.store.apply_validation(p, kid, res)
            self.refresh_all_btn.setEnabled(True)
            self.status.setText("")
            self.refresh()
        job.finished_with.connect(finish)
        job.finished.connect(job.deleteLater)
        self._job = job
        job.start()
