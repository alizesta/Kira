"""Tests for deterministic Game Mode chat command parsing and dispatch."""
import unittest
from types import SimpleNamespace

from kira.chat.command_adapters import create_default_command_registry
from kira.chat.game_mode_commands import parse_game_mode_command


class GameModeCommandParserTests(unittest.TestCase):
    def test_parses_clear_persian_enable_disable_and_status_requests(self):
        self.assertEqual(parse_game_mode_command("گیم مود رو روشن کن"), "enable")
        self.assertEqual(parse_game_mode_command("گیم‌مود را فعال کن"), "enable")
        self.assertEqual(parse_game_mode_command("گیم مود رو خاموش کن"), "disable")
        self.assertEqual(parse_game_mode_command("وضعیت گیم مود چیه؟"), "status")
        self.assertEqual(parse_game_mode_command("گیم مود روشنه؟"), "status")

    def test_parses_clear_english_controls(self):
        self.assertEqual(parse_game_mode_command("turn on game mode"), "enable")
        self.assertEqual(parse_game_mode_command("disable game mode"), "disable")
        self.assertEqual(parse_game_mode_command("is game mode on?"), "status")

    def test_does_not_capture_unrelated_game_requests_or_screen_questions(self):
        self.assertIsNone(parse_game_mode_command("این بازی رو روشن کن"))
        self.assertIsNone(parse_game_mode_command("تو تصویر بازی رو می‌بینی؟"))
        self.assertIsNone(parse_game_mode_command("من روی صفحه بازی‌ام، ویژن مگه نداری؟"))

    def _registry(self, handler):
        tool_agent = SimpleNamespace(
            enabled=lambda: False,
            is_task_running=lambda _session: False,
            planning_enabled=lambda: False,
        )
        return create_default_command_registry(
            permission_checker=None,
            usage_parser=lambda _text: None,
            usage_report=lambda _days: "",
            body_parser=lambda _text: [],
            body_is_active=lambda: False,
            body_handler=lambda _names: None,
            web_parser=lambda _text: (None, False),
            image_parser=lambda _text: ("", False),
            task_control_parser=lambda _text: (None, ""),
            task_running_checker=lambda _session: False,
            tool_agent=tool_agent,
            desktop_action_matcher=lambda _text: None,
            desktop_action_handler=lambda _text: None,
            game_mode_handler=handler,
        )

    def test_chat_command_dispatch_invokes_injected_game_mode_owner(self):
        calls = []
        registry = self._registry(lambda action: calls.append(action) or f"state:{action}")
        try:
            dispatch = registry.dispatch_text(
                "گیم مود رو روشن کن", session_id="kira", request_id="request-1",
            )
            self.assertEqual(calls, ["enable"])
            self.assertTrue(dispatch.handled)
            self.assertEqual(dispatch.reply_text, "state:enable")
        finally:
            registry.close()

    def test_chat_command_executes_and_continues_when_user_attached_an_image(self):
        calls = []
        registry = self._registry(lambda action: calls.append(action) or "handled")
        try:
            dispatch = registry.dispatch_text(
                "گیم مود رو روشن کن",
                session_id="kira",
                request_id="request-2",
                metadata={"has_attachments": True},
            )
            self.assertTrue(dispatch.handled)
            self.assertTrue(dispatch.continue_chat)
            self.assertEqual(calls, ["enable"])
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
