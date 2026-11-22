import unittest
from types import SimpleNamespace
from unittest import mock

from kira.tools.agent import ToolAgent

from kira.game_mode_policy import (
    STORY_MODE, COMPETITIVE_SAFE_MODE, game_mode_permissions,
    normalize_game_mode_profile, tool_categories_allowed,
)


class GameModePolicyTests(unittest.TestCase):
    def test_story_mode_allows_vision_and_local_game_audio(self):
        permissions = game_mode_permissions(STORY_MODE)
        self.assertTrue(permissions["vision_capture"])
        self.assertTrue(permissions["game_audio_loopback"])
        self.assertTrue(permissions["automatic_game_audio_alerts"])
        self.assertTrue(permissions["microphone_wake_word"])

    def test_competitive_safe_allows_read_only_vision_but_disables_game_audio(self):
        permissions = game_mode_permissions(COMPETITIVE_SAFE_MODE)
        self.assertTrue(permissions["vision_capture"])
        self.assertFalse(permissions["game_audio_loopback"])
        self.assertFalse(permissions["automatic_game_audio_alerts"])
        self.assertTrue(permissions["microphone_wake_word"])

    def test_high_risk_capabilities_stay_disabled_in_both_profiles(self):
        for profile in (STORY_MODE, COMPETITIVE_SAFE_MODE):
            permissions = game_mode_permissions(profile)
            for key in ("overlay", "process_memory_read", "process_memory_write",
                        "code_injection", "graphics_api_hooks",
                        "game_file_modification", "driver_installation"):
                self.assertFalse(permissions[key], (profile, key))

    def test_unknown_profile_fails_closed(self):
        self.assertEqual(normalize_game_mode_profile("unknown"), COMPETITIVE_SAFE_MODE)
        self.assertTrue(game_mode_permissions("unknown")["vision_capture"])
        self.assertFalse(game_mode_permissions("unknown")["input_automation"])
        self.assertFalse(game_mode_permissions("unknown")["game_audio_loopback"])

    def test_competitive_safe_only_allows_web_tools(self):
        self.assertTrue(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ("web",)))
        self.assertFalse(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ("desktop",)))
        self.assertFalse(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ("apps",)))
        self.assertFalse(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ("mcp",)))
        self.assertFalse(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ()))
        self.assertFalse(tool_categories_allowed(COMPETITIVE_SAFE_MODE, ("web", "desktop")))

    def test_entering_competitive_safe_cancels_running_tool_tasks(self):
        agent = object.__new__(ToolAgent)
        agent._competitive_safe_mode = False
        agent.registry = SimpleNamespace(access=SimpleNamespace(revoke_grants=mock.Mock()))
        agent._pending_by_session = {}
        agent._pending_new_sessions = set()
        agent.request_cancel = mock.Mock()
        agent.set_competitive_safe_mode(True)
        self.assertTrue(agent._competitive_safe_mode)
        agent.request_cancel.assert_called_once_with()
        agent.set_competitive_safe_mode(True)
        agent.request_cancel.assert_called_once_with()
        agent.set_competitive_safe_mode(False)
        self.assertFalse(agent._competitive_safe_mode)
        agent.request_cancel.assert_called_once_with()

    def test_story_mode_retains_existing_tool_permissions(self):
        self.assertTrue(tool_categories_allowed(STORY_MODE, ("desktop",)))
        self.assertTrue(tool_categories_allowed(STORY_MODE, ("apps",)))

    def test_input_automation_is_profile_specific(self):
        self.assertTrue(game_mode_permissions(STORY_MODE)["input_automation"])
        self.assertFalse(game_mode_permissions(COMPETITIVE_SAFE_MODE)["input_automation"])


if __name__ == "__main__":
    unittest.main()
