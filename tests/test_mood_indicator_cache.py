"""Avoid rebuilding the mood indicator when its visible state is unchanged."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from kira.ui.main_window_session import SessionController
    HAVE_QT = True
except ImportError:  # pragma: no cover - minimal portable environment
    HAVE_QT = False


class _Label:
    def __init__(self):
        self.pixmaps = []
        self.styles = []
        self.tooltips = []
        self.visible = None
        self.clears = 0

    def setPixmap(self, value):
        self.pixmaps.append(value)

    def setStyleSheet(self, value):
        self.styles.append(value)

    def setToolTip(self, value):
        self.tooltips.append(value)

    def setVisible(self, value):
        self.visible = bool(value)

    def clear(self):
        self.clears += 1


class _Icon:
    def pixmap(self, _size):
        return object()


@unittest.skipUnless(HAVE_QT, "PySide6 is required for the session UI contract")
class MoodIndicatorCacheTests(unittest.TestCase):
    def make_controller(self, state):
        face = _Label()
        energy = _Label()
        context = SimpleNamespace(
            views=SimpleNamespace(mood_emotion_icon=face, mood_indicator=energy),
            state=SimpleNamespace(
                cur=SimpleNamespace(cid="kira"),
                _mood_emotion_glow=None,
            ),
            services=SimpleNamespace(
                mood_service=SimpleNamespace(current=lambda character_id: dict(state))
            ),
        )
        controller = SimpleNamespace(
            context=context,
            _sync_mood_character=lambda: None,
            maybe_proactive_checkin=lambda: None,
        )
        return controller, face, energy

    def test_unchanged_mood_does_not_recreate_icons_or_reapply_styles(self):
        state = {
            "emotion": "happy",
            "intensity": 42,
            "behavior": "balanced",
            "energy_label": "normal",
            "secondary_emotions": [],
        }
        controller, face, energy = self.make_controller(state)
        with patch("kira.ui.main_window_session.make_icon", return_value=_Icon()) as make_icon:
            SessionController.update_mood_indicator(controller)
            SessionController.update_mood_indicator(controller)

        make_icon.assert_called_once()
        self.assertEqual(len(face.pixmaps), 1)
        self.assertEqual(len(face.styles), 1)
        self.assertEqual(len(face.tooltips), 1)
        self.assertTrue(face.visible)
        self.assertEqual(energy.clears, 1)
        self.assertFalse(energy.visible)
        self.assertEqual(len(energy.tooltips), 1)

    def test_emotion_face_is_visible_when_rendering_falls_back(self):
        controller, face, energy = self.make_controller({})
        controller.context.services.mood_service.current = lambda character_id: (_ for _ in ()).throw(
            RuntimeError("mood state unavailable")
        )
        with patch("kira.ui.main_window_session.make_icon", return_value=_Icon()):
            SessionController.update_mood_indicator(controller)

        self.assertEqual(len(face.pixmaps), 1)
        self.assertTrue(face.visible)
        self.assertEqual(energy.clears, 1)
        self.assertFalse(energy.visible)

    def test_changed_energy_refreshes_the_indicator(self):
        state = {
            "emotion": "happy",
            "intensity": 42,
            "behavior": "balanced",
            "energy_label": "normal",
            "secondary_emotions": [],
        }
        controller, face, energy = self.make_controller(state)
        with patch("kira.ui.main_window_session.make_icon", return_value=_Icon()) as make_icon:
            SessionController.update_mood_indicator(controller)
            state["energy_label"] = "active"
            controller.context.services.mood_service.current = lambda character_id: dict(state)
            SessionController.update_mood_indicator(controller)

        self.assertEqual(make_icon.call_count, 3)  # face icon for each state, plus the energy glyph
        self.assertEqual(len(face.pixmaps), 2)
        self.assertTrue(face.visible)
        self.assertTrue(energy.visible)
        self.assertEqual(len(energy.pixmaps), 1)


if __name__ == "__main__":
    unittest.main()
