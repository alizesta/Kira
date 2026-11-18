"""Qt-free tests for shared runtime settings application."""
import unittest
from unittest.mock import Mock, patch

from kira.app.runtime_settings_application import RuntimeSettingsApplicationService


class RuntimeSettingsApplicationServiceTests(unittest.TestCase):
    def test_configure_initializes_memory_and_usage_from_same_settings(self):
        settings = {"active_character_id": "ren"}
        with patch("kira.app.runtime_settings_application.evidence_memory.configure") as memory, patch(
            "kira.app.runtime_settings_application.usage.install"
        ) as usage:
            RuntimeSettingsApplicationService.configure(settings)

        memory.assert_called_once_with(settings)
        usage.assert_called_once_with(settings)

    def test_apply_updates_tool_agent_and_shared_consumers(self):
        settings = {"active_character_id": "mika"}
        tool_agent = Mock()
        calls = []
        with patch(
            "kira.app.runtime_settings_application.evidence_memory.configure",
            side_effect=lambda value: calls.append(("memory", value)),
        ), patch(
            "kira.app.runtime_settings_application.usage.install",
            side_effect=lambda value: calls.append(("usage", value)),
        ):
            RuntimeSettingsApplicationService.apply(settings, tool_agent=tool_agent)

        tool_agent.set_settings.assert_called_once_with(settings)
        self.assertEqual(calls, [("memory", settings), ("usage", settings)])

    def test_apply_without_tool_agent_is_supported(self):
        settings = {}
        with patch("kira.app.runtime_settings_application.evidence_memory.configure") as memory, patch(
            "kira.app.runtime_settings_application.usage.install"
        ) as usage:
            RuntimeSettingsApplicationService.apply(settings)

        memory.assert_called_once_with(settings)
        usage.assert_called_once_with(settings)


if __name__ == "__main__":
    unittest.main()
