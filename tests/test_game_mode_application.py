"""Qt-free tests for game-mode application permissions."""
import unittest

from kira.app.game_mode_application import GameModeApplicationService


class GameModeApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GameModeApplicationService()

    def test_unknown_profile_fails_closed_to_competitive_safe(self):
        self.assertEqual(
            self.service.normalize_profile("unknown"),
            self.service.COMPETITIVE_SAFE_MODE,
        )
        permissions = self.service.permissions("unknown")
        self.assertFalse(permissions["input_automation"])
        self.assertTrue(permissions["vision_capture"])
        self.assertFalse(permissions["game_audio_loopback"])

    def test_story_profile_enables_declared_game_capabilities(self):
        self.assertTrue(self.service.is_story("story"))
        self.assertTrue(self.service.can_capture_vision("story"))
        self.assertTrue(self.service.can_use_game_audio_loopback("story"))
        self.assertTrue(self.service.can_emit_automatic_game_audio_alerts("story"))
        self.assertTrue(self.service.can_use_input_automation("story"))

    def test_competitive_safe_denies_local_control_but_allows_web_research(self):
        profile = self.service.COMPETITIVE_SAFE_MODE
        self.assertTrue(self.service.is_competitive_safe(profile))
        self.assertFalse(self.service.can_use_input_automation(profile))
        self.assertTrue(self.service.can_capture_vision(profile))
        self.assertTrue(self.service.tool_categories_allowed(profile, {"web"}))
        self.assertFalse(self.service.tool_categories_allowed(profile, {"web", "desktop"}))

    def test_game_audio_alert_policy_classifies_and_throttles_important_events(self):
        urgent = self.service.classify_game_audio(
            "Low health warning",
            now=100.0,
            enabled=True,
            profile="story",
            busy=False,
            speaking=False,
        )
        self.assertEqual(urgent.category, "urgent")
        self.assertEqual(urgent.emotion, "surprised")
        self.assertIsNone(
            self.service.classify_game_audio(
                "Low health warning",
                now=130.0,
                enabled=True,
                profile="story",
                busy=False,
                speaking=False,
            )
        )
        complete = self.service.classify_game_audio(
            "Mission complete",
            now=131.0,
            enabled=True,
            profile="story",
            busy=False,
            speaking=False,
        )
        self.assertEqual(complete.category, "complete")

    def test_game_audio_alert_policy_suppresses_irrelevant_busy_or_disallowed_events(self):
        kwargs = {
            "now": 100.0,
            "enabled": True,
            "profile": "story",
            "busy": False,
            "speaking": False,
        }
        self.assertIsNone(self.service.classify_game_audio("hello friend", **kwargs))
        self.assertIsNone(
            self.service.classify_game_audio("Low health", **{**kwargs, "busy": True})
        )
        self.assertIsNone(
            self.service.classify_game_audio("Low health", **{**kwargs, "speaking": True})
        )
        self.assertIsNone(
            self.service.classify_game_audio(
                "Low health", **{**kwargs, "profile": self.service.COMPETITIVE_SAFE_MODE}
            )
        )

    def test_command_policy_denies_desktop_launch_only_when_profile_disallows_it(self):
        self.assertIsNone(
            self.service.command_denial_reason("story", {"desktop.launch"})
        )
        self.assertIn(
            "Competitive Safe",
            self.service.command_denial_reason(
                "competitive_safe", {"desktop.launch"}
            ),
        )
        self.assertIsNone(
            self.service.command_denial_reason(
                "competitive_safe", {"web.search"}
            )
        )


if __name__ == "__main__":
    unittest.main()
