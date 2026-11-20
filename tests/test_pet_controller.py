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
        self.assertEqual((window.x(), window.y()), (240, 130))
        self.assertTrue(pet.release())
        self.assertEqual(pet.state, "free")

    def test_small_movement_is_a_click_not_a_drag(self):
        _, pet, _ = make({})
        pet.press(QPoint(10, 10))
        pet.move(QPoint(12, 11))
        self.assertFalse(pet.release())

    def test_released_character_falls_and_sits_on_the_floor(self):
        window, pet, commands = make({"companion_hang": False})
        window.move(300, 0)
        pet.press(QPoint(310, 10))
        pet.move(QPoint(330, 20))
        self.assertEqual(pet.state, "dragging")
        pet.release()
        self.assertEqual(pet.state, "falling")
        for _ in range(2000):
            if pet.state != "falling":
                break
            pet._fall_tick()
        self.assertEqual(pet.state, "perched")
        self.assertIn("sit", commands[-1])
        self.assertIsNotNone(pet.surface)

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
