"""Qt-free tests for Vision application policy."""
import unittest

from kira.app.game_mode_application import GameModeApplicationService
from kira.app.vision_application import VisionApplicationService
from kira.app.desktop_capture_application import DesktopCaptureApplicationService


class VisionApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.game_mode = GameModeApplicationService()
        self.service = VisionApplicationService(self.game_mode, "economic")

    def test_capture_requires_manual_enablement_but_supports_both_profiles(self):
        self.assertFalse(self.service.capture_allowed(False, "story"))
        self.assertFalse(self.service.capture_allowed(False, "competitive_safe"))
        self.assertTrue(self.service.capture_allowed(True, "story"))
        self.assertTrue(self.service.capture_allowed(True, "competitive_safe"))

    def test_unknown_mode_falls_back_to_economic_policy(self):
        policy = self.service.set_mode("not-a-mode")
        self.assertEqual(policy.name, "economic")
        self.assertEqual(self.service.frame_gate.policy.name, "economic")

    def test_analysis_is_suppressed_when_chat_or_provider_is_busy(self):
        common = dict(
            enabled=True, profile="story", frame_available=True,
            worker_running=False, chat_busy=False, provider_busy=False,
            speech_active=False,
        )
        self.assertTrue(self.service.should_analyze(**common))
        for key in ("worker_running", "chat_busy", "provider_busy", "speech_active"):
            blocked = dict(common)
            blocked[key] = True
            self.assertFalse(self.service.should_analyze(**blocked), key)

    def test_analysis_requires_a_frame_and_permitted_game_mode(self):
        common = dict(
            enabled=True, profile="story", frame_available=False,
            worker_running=False, chat_busy=False, provider_busy=False,
            speech_active=False,
        )
        self.assertFalse(self.service.should_analyze(**common))
        common["frame_available"] = True
        common["profile"] = "competitive_safe"
        self.assertTrue(self.service.should_analyze(**common))

    def test_result_is_deduplicated_and_disabled_capture_is_silent(self):
        self.assertEqual(
            self.service.consume_result(enabled=True, profile="story", ok=True, result="enemy ahead"),
            "enemy ahead",
        )
        self.assertIsNone(
            self.service.consume_result(enabled=True, profile="story", ok=True, result="enemy ahead")
        )
        self.assertIsNone(
            self.service.consume_result(enabled=False, profile="story", ok=True, result="new scene")
        )
        self.assertEqual(
            self.service.consume_result(enabled=True, profile="story", ok=True, result="new scene"),
            "new scene",
        )

    def test_desktop_source_uses_independent_manual_privacy_gate(self):
        desktop = DesktopCaptureApplicationService()
        service = VisionApplicationService(self.game_mode, "economic", desktop)
        identity = {
            "hwnd": 10, "pid": 20, "exe": "browser.exe", "title": "Work tab",
            "path": r"C:\Program Files\Browser.exe", "rect": (0, 0, 900, 700),
        }
        self.assertFalse(service.capture_allowed(
            False, None, source="desktop", window_info=identity
        ))
        desktop.set_enabled(True)
        self.assertTrue(service.capture_allowed(
            False, None, source="desktop", window_info=identity
        ))
        blocked = dict(identity, title="New Tab - Incognito")
        self.assertFalse(service.capture_allowed(
            False, None, source="desktop", window_info=blocked
        ))
        self.assertFalse(service.capture_allowed(
            False, None, source="unknown", window_info=identity
        ))

    def test_explicit_desktop_source_accepts_partial_foreground_identity(self):
        desktop = DesktopCaptureApplicationService()
        desktop.set_enabled(True)
        service = VisionApplicationService(self.game_mode, "economic", desktop)
        partial = {
            "hwnd": 10, "pid": 20, "exe": "", "title": "", "path": "",
            "rect": (0, 0, 900, 700),
        }
        self.assertFalse(service.capture_allowed(
            False, None, source="desktop", window_info=partial
        ))
        self.assertTrue(service.capture_allowed(
            False, None, source="desktop", window_info=partial,
            allow_partial_identity=True,
        ))
        self.assertTrue(service.should_analyze(
            enabled=True, profile=None, frame_available=True,
            worker_running=False, chat_busy=False, provider_busy=False,
            speech_active=False, source="desktop", window_info=partial,
            allow_partial_identity=True,
        ))

    def test_reset_clears_duplicate_suppression_and_frame_gate(self):
        self.service.consume_result(enabled=True, profile="story", ok=True, result="scene")
        self.service.reset()
        self.assertEqual(self.service.last_note, "")
        self.assertEqual(
            self.service.consume_result(enabled=True, profile="story", ok=True, result="scene"),
            "scene",
        )


if __name__ == "__main__":
    unittest.main()
