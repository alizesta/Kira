import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kira.ui.components.api_panel import ApiPanel
from kira.ui.components.models_panel import ModelsPanel

APP = QApplication.instance() or QApplication([])


def row(model, tabs, **kw):
    base = {"provider": "groq", "provider_label": "Groq", "model": model, "price": "free", "free": True, "status": "available",
            "enabled": "active" in tabs, "route_id": "r", "reason": "", "tabs": tabs, "restorable": True, "test": None, "order": 0}
    base.update(kw)
    return base


class ModelsPanelTests(unittest.TestCase):
    def test_rows_land_in_their_tabs_and_counts_show(self):
        panel = ModelsPanel()
        panel.set_rows([row("a-very-long-model-name-001", ["active", "free"]), row("b", ["paid"], price="paid", free=False),
                        row("c", ["archived"], reason="x")])
        self.assertEqual([panel.tables[t].rowCount() for t in ("active", "free", "paid", "archived")], [1, 1, 1, 1])
        self.assertIn("(1)", panel.tabs.tabText(0))
        self.assertEqual(panel.tables["active"].item(0, 1).text(), "a-very-long-model-name-001")

    def test_signals_and_filter(self):
        panel = ModelsPanel()
        panel.set_rows([row("alpha", ["active", "free"]), row("beta", ["free"], enabled=False)])
        got = []
        panel.test_requested.connect(lambda p, m: got.append(("test", p, m)))
        panel.archive_requested.connect(lambda p, m: got.append(("arch", p, m)))
        panel.tables["free"].cellWidget(0, 5).findChild(type(panel.refresh_btn)).click()
        panel.tables["free"].cellWidget(0, 6).findChild(type(panel.refresh_btn)).click()
        self.assertEqual(got, [("test", "groq", "alpha"), ("arch", "groq", "alpha")])
        panel.apply_filter("beta")
        self.assertTrue(panel.tables["free"].isRowHidden(0))
        self.assertFalse(panel.tables["free"].isRowHidden(1))
        panel.set_testing("groq", "alpha", True)
        self.assertFalse(panel.tables["free"].cellWidget(0, 5).findChild(type(panel.refresh_btn)).isEnabled())


class ApiPanelTests(unittest.TestCase):
    def test_rows_and_buttons(self):
        panel = ApiPanel()
        panel.set_rows([{"id": "groq", "label": "Groq", "key": "gsk_…1234", "status": "valid", "enabled": True, "accessible": 3,
                         "active": 1, "checked_at": 0, "error": ""}], status_text=lambda c: c, time_text=lambda t: "-")
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.selected_id(), "groq")
        got = []
        panel.delete_requested.connect(got.append)
        panel.table.cellWidget(0, 5).findChildren(type(panel.add_btn))[1].click()
        self.assertEqual(got, ["groq"])


if __name__ == "__main__":
    unittest.main()
