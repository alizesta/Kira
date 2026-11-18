"""Compatibility tests for the existing Kira command adapters."""
import unittest

from kira.chat.command_adapters import create_default_command_registry
from kira.chat.commands import CommandStatus, PermissionDecision


class FakeTasks:
    def active(self, session_id):
        return object() if session_id == "character-kira" else None


class FakeToolAgent:
    def __init__(self):
        self.is_enabled = True
        self._running_plan_sessions = {"character-kira"}
        self.tasks = FakeTasks()
        self.calls = []

    def enabled(self):
        return self.is_enabled

    def planning_enabled(self):
        return True

    def is_task_running(self, session_id):
        return session_id in self._running_plan_sessions

    def has_pending(self, session_id):
        return session_id == "character-kira"

    def handle_confirmation_reply(self, text, *, session_id):
        self.calls.append(("confirm", session_id, text))
        return "confirmed"

    def handle_task_command(self, text, *, session_id):
        self.calls.append(("task", session_id, text))
        return "task-status"

    def control_running(self, text, *, session_id):
        self.calls.append(("running", session_id, text))
        return "running-status"


class ChatCommandAdapterTests(unittest.TestCase):
    def setUp(self):
        self.agent = FakeToolAgent()
        self.desktop_calls = []
        self.registry = create_default_command_registry(
            permission_checker=lambda command, _request: (
                PermissionDecision(False, "desktop denied")
                if "desktop.launch" in command.required_permissions else True
            ),
            usage_parser=lambda text: 7 if text.startswith("/usage") else None,
            usage_report=lambda days: f"usage:{days}",
            body_parser=lambda text: ["wave"] if "wave" in text else [],
            body_is_active=lambda: True,
            body_handler=lambda names: self.desktop_calls.append(("body", names)),
            web_parser=lambda text: (
                (text.split(maxsplit=1)[1], True)
                if text.startswith("/web ") else (None, False)
            ),
            image_parser=lambda text: (text, True),
            task_control_parser=lambda text: (
                ("pause", "") if "pause" in text else
                ("status", "") if "status" in text else
                (None, "")
            ),
            task_running_checker=self.agent.is_task_running,
            tool_agent=self.agent,
            desktop_action_matcher=lambda text: "notepad" if "notepad" in text else None,
            desktop_action_handler=lambda text: self.desktop_calls.append(("desktop", text)) or "opened",
        )

    def tearDown(self):
        self.registry.close()

    def test_existing_usage_and_web_slash_commands_are_adapted(self):
        usage = self.registry.dispatch_text(
            "/usage 7", session_id="runtime-kira", request_id="usage-1",
        )
        self.assertEqual(usage.reply_text, "usage:7")
        web = self.registry.dispatch_text(
            "/web latest release", session_id="runtime-kira", request_id="web-1",
        )
        self.assertTrue(web.continue_chat)
        self.assertEqual(web.rewritten_text, "latest release")
        self.assertTrue(web.metadata["force_web_search"])

    def test_image_search_requires_an_attached_image_and_preserves_query(self):
        without_image = self.registry.dispatch_text(
            "/img identify this", session_id="runtime-kira", request_id="image-1",
            metadata={"has_attachments": True, "has_image": False},
        )
        self.assertFalse(without_image.handled)

        with_image = self.registry.dispatch_text(
            "/img identify this", session_id="runtime-kira", request_id="image-2",
            metadata={"has_attachments": True, "has_image": True},
        )
        self.assertTrue(with_image.handled)
        self.assertTrue(with_image.continue_chat)
        self.assertEqual(with_image.rewritten_text, "identify this")
        self.assertTrue(with_image.metadata["force_image_search"])

    def test_allowed_desktop_shortcut_delegates_to_existing_safe_action(self):
        self.registry._permission_checker = lambda _command, _request: True
        result = self.registry.dispatch_text(
            "open notepad", session_id="runtime-kira", request_id="desktop-allowed",
        )
        self.assertEqual(result.reply_text, "opened")
        self.assertEqual(self.desktop_calls, [("desktop", "open notepad")])

    def test_body_command_is_delegated_to_existing_body_owner(self):
        result = self.registry.dispatch_text(
            "please wave", session_id="runtime-kira", request_id="body-1",
        )
        self.assertTrue(result.handled)
        self.assertTrue(result.continue_chat)
        self.assertEqual(self.desktop_calls, [("body", ["wave"])])

    def test_running_task_control_uses_character_identity_not_runtime_session(self):
        result = self.registry.dispatch_text(
            "pause", session_id="runtime-kira", request_id="control-1",
            metadata={"character_id": "character-kira"},
        )
        self.assertEqual(result.reply_text, "running-status")
        self.assertEqual(self.agent.calls, [
            ("running", "character-kira", "pause"),
        ])

    def test_pending_confirmation_uses_character_identity(self):
        result = self.registry.dispatch_text(
            "تأیید", session_id="runtime-kira", request_id="confirm-1",
            metadata={"character_id": "character-kira"},
        )
        self.assertEqual(result.reply_text, "confirmed")
        self.assertEqual(self.agent.calls, [
            ("confirm", "character-kira", "تأیید"),
        ])

    def test_task_control_uses_character_identity_when_not_running(self):
        self.agent._running_plan_sessions.clear()
        result = self.registry.dispatch_text(
            "status", session_id="runtime-kira", request_id="task-1",
            metadata={"character_id": "character-kira"},
        )
        self.assertEqual(result.reply_text, "task-status")
        self.assertEqual(self.agent.calls, [
            ("task", "character-kira", "status"),
        ])

    def test_desktop_shortcut_permission_denial_prevents_execution(self):
        self.agent.is_enabled = False
        result = self.registry.dispatch_text(
            "open notepad", session_id="runtime-kira", request_id="desktop-1",
        )
        self.assertEqual(result.results[0].status, CommandStatus.REJECTED)
        self.assertEqual(result.reply_text, "desktop denied")
        self.assertEqual(self.desktop_calls, [])


if __name__ == "__main__":
    unittest.main()
