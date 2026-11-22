"""Regression tests for Kira's automatic deterministic command fast path."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from kira.tools.fast_commands import parse_fast_command


class FastCommandParserTests(unittest.TestCase):
    def assertTool(self, text, tool, args=None):
        result = parse_fast_command(text)
        self.assertIsNotNone(result, text)
        self.assertEqual(result["tool"], tool)
        if args is not None:
            self.assertEqual(result["args"], args)

    def test_datetime_persian_and_english(self):
        for text in ("ساعت چنده؟", "الان ساعت چنده", "تاریخ امروز چیه", "what time is it", "today's date"):
            self.assertTool(text, "get_datetime", {})

    def test_bluetooth_status_and_switch(self):
        self.assertTool("وضعیت بلوتوث چیه", "bluetooth_status", {})
        self.assertTool("بلوتوث روشنه؟", "bluetooth_status", {})
        self.assertTool("bluetooth status", "bluetooth_status", {})
        self.assertTool("بلوتوث رو روشن کن", "bluetooth_on", {})
        self.assertTool("turn bluetooth off", "bluetooth_off", {})

    def test_volume_set_and_relative_commands(self):
        self.assertTool("صدا رو روی ۵۰ درصد بذار", "audio_set_volume", {"percent": 50})
        self.assertTool("ولوم رو 30 کن", "audio_set_volume", {"percent": 30})
        self.assertTool("set volume to 35%", "audio_set_volume", {"percent": 35})
        self.assertTool("صدا رو زیاد کن", "audio_change_volume", {"direction": "up", "amount": 10})
        self.assertTool("volume down", "audio_change_volume", {"direction": "down", "amount": 10})

    def test_mute_and_unmute_are_not_confused(self):
        self.assertTool("صدای سیستم رو بی صدا کن", "audio_mute", {})
        self.assertTool("mute the speakers", "audio_mute", {})
        self.assertTool("صدا رو از حالت میوت دربیار", "audio_unmute", {})
        self.assertTool("unmute the speakers", "audio_unmute", {})

    def test_open_app_preserves_user_language(self):
        self.assertTool("کروم رو باز کن", "open_app", {"name": "کروم"})
        self.assertTool("برنامه دیسکورد رو باز کن", "open_app", {"name": "دیسکورد"})
        self.assertTool("open Discord", "open_app", {"name": "discord"})

    def test_ambiguous_or_unsafe_requests_fall_through(self):
        for text in (
            "این کار رو انجام بده", "فایل گزارش رو باز کن", "open https://example.com",
            "open the report.pdf", "open Discord and search the web", "volume to 250 percent",
            "حذف فایل گزارش", "open C:\\secret",
        ):
            self.assertIsNone(parse_fast_command(text), text)


class _Access:
    @contextmanager
    def use_session(self, _owner):
        yield


class _Registry:
    def __init__(self, status="ok"):
        from kira.tools.registry import ToolResult
        self.access = _Access()
        self.user_text = ""
        self.calls = []
        self.status = status
        self.tool = SimpleNamespace(name="audio_set_volume", categories=("audio",), level=2,
                                    external=False, memo=None)
        self.ToolResult = ToolResult

    def get(self, name):
        return self.tool if name == self.tool.name else None

    def execute(self, name, args):
        self.calls.append((name, args))
        message = ("ولوم سیستم روی ۵۰ درصد تنظیم شد و دوباره بررسی شد."
                   if self.status == "ok" else "Windows audio endpoint unavailable")
        return self.ToolResult(name, self.status, message, args, 2, 4)


class _NoModelRouter:
    def chat_stream(self, *args, **kwargs):
        raise AssertionError("Fast Path must not call the language model")

    def chat_with_tools(self, *args, **kwargs):
        raise AssertionError("Fast Path must not call the language model")


class FastPathIntegrationTests(unittest.TestCase):
    def _agent(self, status="ok"):
        from kira.tools.agent import ToolAgent
        agent = ToolAgent.__new__(ToolAgent)
        agent.settings = {"tools_mode": "auto", "agent_planning": "off"}
        agent.registry = _Registry(status)
        agent._competitive_safe_mode = False
        agent._pending_by_session = {}
        agent._pending_new_sessions = set()
        agent._init_session_turn_states()
        return agent

    def test_simple_command_runs_registry_without_model_round_trip(self):
        agent = self._agent()
        plan = agent.plan("صدا رو روی ۵۰ درصد بذار", session_id="kira")
        self.assertEqual(plan.fast_call, {"tool": "audio_set_volume", "args": {"percent": 50}, "category": "audio"})
        chunks = []
        result = agent.run(_NoModelRouter(), [{"role": "user", "content": "صدا رو روی ۵۰ درصد بذار"}],
                           "system", 0.2, plan, on_chunk=chunks.append)
        self.assertTrue(result["fast_path"])
        self.assertIn("تنظیم شد", result["text"])
        self.assertEqual(agent.registry.calls, [("audio_set_volume", {"percent": 50})])
        self.assertEqual(chunks, [result["text"]])

    def test_tool_failure_is_reported_without_false_success(self):
        from kira.tools.registry import ERROR
        agent = self._agent(ERROR)
        plan = agent.plan("صدا رو روی ۵۰ درصد بذار", session_id="kira")
        result = agent.run(_NoModelRouter(), [{"role": "user", "content": "صدا رو روی ۵۰ درصد بذار"}],
                           "system", 0.2, plan)
        self.assertIn("❌", result["text"])
        self.assertNotIn("✅", result["text"])
        self.assertIn("Windows audio endpoint unavailable", result["text"])


if __name__ == "__main__":
    unittest.main()
