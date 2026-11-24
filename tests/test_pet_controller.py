import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication, QWidget

from kira.pet import PetController

APP = QApplication.instance() or QApplication([])


class FakeAnimator(QObject):
    body = Signal(str)


def make(settings):
    window = QWidget()
    window.resize(300, 600)
    window.move(200, 100)
    animator = FakeAnimator()
    commands = []
    animator.body.connect(commands.append)
    pet = PetController(window, animator, settings)
    window.pet = pet
    return window, pet, commands


class PetControllerTests(unittest.TestCase):
    def test_plain_drag_when_perch_and_hang_are_off(self):
        window, pet, _ = make({"companion_perch": False, "companion_hang": False})
        pet.press(QPoint(300, 300))
        pet.move(QPoint(340, 330))
        area = QApplication.primaryScreen().availableGeometry()
        self.assertGreaterEqual(window.x(), area.left())
        self.assertGreaterEqual(window.y(), area.top())
        self.assertLessEqual(window.x() + window.width() - 1, area.right())
        self.assertLessEqual(window.y() + window.height() - 1, area.bottom())
        self.assertTrue(pet.release())
        self.assertEqual(pet.state, "free")

    def test_plain_drag_cannot_move_any_part_of_the_companion_off_screen(self):
        window, pet, _ = make({"companion_perch": False, "companion_hang": False})
        area = QApplication.primaryScreen().availableGeometry()
        window.resize(120, 160)
        window.move(area.left() + 5, area.top() + 5)
        pet.press(QPoint(area.left() + 10, area.top() + 10))
        pet.move(QPoint(area.right() + 200, area.bottom() + 200))
        self.assertGreaterEqual(window.x(), area.left())
        self.assertGreaterEqual(window.y(), area.top())
        self.assertLessEqual(window.x() + window.width() - 1, area.right())
        self.assertLessEqual(window.y() + window.height() - 1, area.bottom())

    def test_small_movement_is_a_click_not_a_drag(self):
        _, pet, _ = make({})
        pet.press(QPoint(10, 10))
        pet.move(QPoint(12, 11))
        self.assertFalse(pet.release())

    def test_released_character_stays_put_when_no_perch_target_is_nearby(self):
        window, pet, _ = make({})
        window.move(200, 100)
        from kira.perch import Surface
        pet._screen = lambda: object()
        pet._surfaces = lambda _screen: [Surface(0, 1000, 1100, "window", 1)]
        pet._floor = lambda _screen: Surface(0, 1200, 1200, "floor")
        pet._begin_drag()
        original_pos = window.pos()
        pet._end_drag()
        self.assertEqual(pet.state, "free")
        self.assertEqual(window.pos(), original_pos)
        self.assertFalse(pet._tick.isActive())

    def test_released_character_falls_when_feet_are_near_a_window_top(self):
        window, pet, _ = make({})
        window.resize(300, 600)
        window.move(200, 100)
        from kira.perch import Surface
        pet._screen = lambda: object()
        pet._surfaces = lambda _screen: [Surface(150, 700, 760, "window", 1)]
        pet._floor = lambda _screen: Surface(0, 1200, 1300, "floor")
        pet._begin_drag()
        pet._end_drag()
        self.assertEqual(pet.state, "falling")
        pet._tick.stop()

    def test_released_character_falls_when_feet_are_near_the_taskbar(self):
        window, pet, _ = make({})
        window.resize(300, 600)
        window.move(200, 100)
        from kira.perch import Surface
        feet_y = 100 + 600 * 0.97
        pet._screen = lambda: object()
        pet._surfaces = lambda _screen: []
        pet._floor = lambda _screen: Surface(0, 1200, feet_y + 80, "taskbar")
        pet._begin_drag()
        pet._end_drag()
        self.assertEqual(pet.state, "falling")
        pet._tick.stop()

    def test_released_character_does_not_fall_at_an_ordinary_screen_edge(self):
        window, pet, _ = make({})
        window.resize(300, 600)
        window.move(200, 100)
        from kira.perch import Surface
        feet_y = 100 + 600 * 0.97
        pet._screen = lambda: object()
        pet._surfaces = lambda _screen: []
        pet._floor = lambda _screen: Surface(0, 1200, feet_y + 80, "floor")
        pet._begin_drag()
        pet._end_drag()
        self.assertEqual(pet.state, "free")
        self.assertFalse(pet._tick.isActive())

    def test_music_makes_a_perched_character_stand_up_and_stop_makes_her_sit(self):
        window, pet, commands = make({})
        from kira.perch import Surface
        pet.state, pet.surface = "perched", Surface(0, 1920, 900, "floor")
        pet.on_music({"on": True, "level": 0.5, "bpm": 120, "beats": 1})
        self.assertTrue(pet._dancing)
        self.assertIn("stand_up", commands[-1])
        pet.on_music({"on": False, "level": 0, "bpm": 0, "beats": 1})
        self.assertFalse(pet._dancing)
        self.assertIn("sit", commands[-1])

    def test_auto_dance_off_never_dances(self):
        _, pet, _ = make({"auto_dance": False})
        pet.state = "free"
        pet.on_music({"on": True, "level": 1, "bpm": 100, "beats": 1})
        self.assertFalse(pet._dancing)


if __name__ == "__main__":
    unittest.main()
