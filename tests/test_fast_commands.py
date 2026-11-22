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


    def test_system_information_queries(self):
        for text in ("مشخصات سیستم چیه", "اطلاعات کامپیوتر", "system specs", "show pc information"):
            self.assertTool(text, "get_system_info", {})

    def test_resource_usage_queries_extract_metric(self):
        cases = (
            ("چقدر رم مصرف شده", "ram"),
            ("مصرف CPU چقدره", "cpu"),
            ("وضعیت کارت گرافیک چیه", "gpu"),
            ("درصد باتری چقدره", "battery"),
            ("system resource usage", "all"),
            ("RAM usage", "ram"),
            ("how much memory is being used", "ram"),
            ("battery status", "battery"),
        )
        for text, part in cases:
            self.assertTool(text, "get_resource_usage", {"part": part})

    def test_disk_and_network_information_queries(self):
        for text in ("فضای خالی درایوها چقدره", "free disk space", "how much storage space is free"):
            self.assertTool(text, "get_disks", {})
        for text in ("وضعیت اینترنت چطوره", "آی پی من چیه", "network info", "am i connected to the internet"):
            self.assertTool(text, "get_network_info", {})

    def test_running_apps_and_active_window_queries(self):
        for text in ("چه برنامه هایی الان باز هستند", "لیست برنامه های در حال اجرا", "what apps are running"):
            self.assertTool(text, "list_running_apps", {})
        for text in ("پنجره فعال چیه", "الان من توی چه برنامه ای هستم", "what app am i currently using"):
            self.assertTool(text, "get_active_window", {})

    def test_incomplete_or_compound_system_requests_fall_through(self):
        for text in (
            "رم", "سیستم رو بررسی کن", "باتری رو درست کن", "فضای دیسک و بعد کروم رو باز کن",
            "show all apps and open Discord", "public IP address",
        ):
            self.assertIsNone(parse_fast_command(text), text)

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
    def __init__(self, status="ok", tool_name="audio_set_volume"):
        from kira.tools.registry import ToolResult
        self.access = _Access()
        self.user_text = ""
        self.calls = []
        self.status = status
        metadata = {
            "audio_set_volume": (("audio",), 2),
            "get_system_info": (("system",), 1),
            "get_resource_usage": (("system",), 1),
            "get_disks": (("system", "files"), 1),
            "get_network_info": (("system",), 1),
            "list_running_apps": (("apps", "system"), 1),
            "get_active_window": (("apps",), 1),
        }
        self.tools = {
            name: SimpleNamespace(name=name, categories=cats, level=level, external=False, memo=None)
            for name, (cats, level) in metadata.items()
        }
        self.tool = self.tools[tool_name]
        self.ToolResult = ToolResult

    def get(self, name):
        return self.tools.get(name)

    def execute(self, name, args):
        self.calls.append((name, args))
        if self.status == "ok":
            message = ("مشخصات واقعی سیستم خوانده شد."
                       if name == "get_system_info" else "ولوم سیستم روی ۵۰ درصد تنظیم شد و دوباره بررسی شد.")
        else:
            message = "Windows audio endpoint unavailable"
        tool = self.get(name)
        return self.ToolResult(name, self.status, message, args, tool.level, 4)


class _NoModelRouter:
    def chat_stream(self, *args, **kwargs):
        raise AssertionError("Fast Path must not call the language model")

    def chat_with_tools(self, *args, **kwargs):
        raise AssertionError("Fast Path must not call the language model")


class FastPathIntegrationTests(unittest.TestCase):
    def _agent(self, status="ok", tool_name="audio_set_volume"):
        from kira.tools.agent import ToolAgent
        agent = ToolAgent.__new__(ToolAgent)
        agent.settings = {"tools_mode": "auto", "agent_planning": "off"}
        agent.registry = _Registry(status, tool_name)
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


    def test_read_only_system_query_runs_without_model_round_trip(self):
        agent = self._agent(tool_name="get_system_info")
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertEqual(plan.fast_call, {"tool": "get_system_info", "args": {}, "category": "system"})
        result = agent.run(_NoModelRouter(), [{"role": "user", "content": "مشخصات سیستم چیه"}],
                           "system", 0.2, plan)
        self.assertTrue(result["fast_path"])
        self.assertIn("مشخصات واقعی سیستم", result["text"])
        self.assertEqual(agent.registry.calls, [("get_system_info", {})])

    def test_competitive_safe_still_blocks_local_fast_path(self):
        agent = self._agent(tool_name="get_system_info")
        agent._competitive_safe_mode = True
        self.assertIsNone(agent.plan("مشخصات سیستم چیه", session_id="kira"))

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
