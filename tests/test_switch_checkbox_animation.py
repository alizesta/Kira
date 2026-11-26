import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPropertyAnimation
from PySide6.QtWidgets import QApplication

from kira.ui.components.switch_checkbox import SwitchCheckBox

_APP = QApplication.instance() or QApplication([])


class SwitchCheckBoxAnimationTests(unittest.TestCase):
    def test_hidden_switch_jumps_to_its_state(self):
        switch = SwitchCheckBox("x")
        switch.setChecked(True)
        self.assertEqual(switch.progress, 1.0)
        self.assertNotEqual(switch._animation.state(), QPropertyAnimation.State.Running)
        switch.setChecked(False)
        self.assertEqual(switch.progress, 0.0)

    def test_visible_switch_animates_and_lands_on_target(self):
        switch = SwitchCheckBox("x")
        switch.show()
        switch.setChecked(True)
        self.assertEqual(switch._animation.state(), QPropertyAnimation.State.Running)
        self.assertLess(switch.progress, 1.0)
        switch._animation.setCurrentTime(switch._animation.duration())
        self.assertEqual(switch.progress, 1.0)
        switch.close()

    def test_rapid_toggle_ends_on_latest_state(self):
        switch = SwitchCheckBox("x")
        switch.show()
        switch.setChecked(True)
        switch.setChecked(False)
        switch._animation.setCurrentTime(switch._animation.duration())
        self.assertEqual(switch.progress, 0.0)
        self.assertFalse(switch.isChecked())
        switch.close()

    def test_checkbox_contract_is_unchanged(self):
        switch = SwitchCheckBox("label")
        seen = []
        switch.toggled.connect(seen.append)
        switch.setChecked(True)
        switch.setChecked(False)
        self.assertEqual(seen, [True, False])
        self.assertEqual(switch.text(), "label")

    def test_progress_is_clamped(self):
        switch = SwitchCheckBox()
        switch.progress = 7.0
        self.assertEqual(switch.progress, 1.0)
        switch.progress = -3.0
        self.assertEqual(switch.progress, 0.0)


if __name__ == "__main__":
    unittest.main()
