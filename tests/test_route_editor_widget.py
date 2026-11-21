"""RouteEditor stays compact: no up/down/default buttons, one Benchmark menu button."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QComboBox
    HAVE_QT = True
except Exception:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class RouteEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        from kira.ui.components.route_editor import RouteEditor

        def combo(_text):
            box = QComboBox()
            box.setEditable(True)
            return box
        return RouteEditor({}, model_combo_factory=combo)

    def test_removed_controls_are_gone(self):
        editor = self.make()
        for name in ("route_up_btn", "route_down_btn", "route_default_btn", "route_bench_all_btn"):
            self.assertFalse(hasattr(editor, name), name)

    def test_route_list_is_compact_and_uses_vertical_scrolling(self):
        editor = self.make()
        self.assertLessEqual(editor.route_list.maximumHeight(), 96)
        self.assertEqual(editor.route_list.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(editor.route_list.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)


    def test_benchmark_is_one_menu_button_with_two_choices(self):
        editor = self.make()
        got = []
        editor.benchmark_requested.connect(got.append)
        actions = editor.route_bench_btn.menu().actions()
        self.assertEqual(len(actions), 2)
        for action in actions:
            action.trigger()
        self.assertEqual(got, [False, True])

    def test_button_count_is_small(self):
        from PySide6.QtWidgets import QPushButton
        editor = self.make()
        self.assertLessEqual(len(editor.findChildren(QPushButton)), 6)


if __name__ == "__main__":
    unittest.main()
