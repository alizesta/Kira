"""Cheap model-owned triage: ordinary chat costs one small call, a PC task escalates to the full catalog/planner."""
import threading
import unittest
from types import SimpleNamespace

from kira.tools import protocol
from kira.tools.access import PathPolicy
from kira.tools.agent import ToolAgent
from kira.tools.builtin import build_registry
from kira.tools.tasks import P_RUNNING

USE_TOOLS_REPLY = '<kira_tool>{"tool": "use_tools", "args": {}}</kira_tool>'


class _ScriptedRouter:
    """Returns the scripted replies in order and records every system prompt it was given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def chat_stream(self, messages, system_prompt, temperature, on_chunk=None, on_event=None, retry_index=0, **_):
        self.prompts.append(system_prompt)
        text = self.replies.pop(0)
        if on_chunk:
            on_chunk(text)
        return {"text": text, "stopped": False, "interrupted": None}


def _agent(**settings):
    agent = ToolAgent.__new__(ToolAgent)
    agent.settings = {"tools_mode": "auto", "agent_planning": "off", **settings}
    agent.registry = build_registry(PathPolicy({}))
    agent._competitive_safe_mode = False
    agent._pending_by_session = {}
    agent._pending_new_sessions = set()
    agent._init_session_turn_states()
    return agent


class TriagePlanTests(unittest.TestCase):
    def test_text_without_task_signal_gets_a_triage_plan(self):
        plan = _agent().plan("سلام، حالت چطوره؟", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertTrue(plan.index_only)
        self.assertFalse(plan.complex)

    def test_unknown_phrasing_is_not_dropped_by_the_prefilter(self):
        plan = _agent().plan("یه والپیپر زنده‌ی پورشه بذار برام", session_id="kira")
        self.assertIsNotNone(plan)                       # reaches the model, which decides

    def test_known_task_signal_skips_triage(self):
        plan = _agent().plan("فایل‌های دسکتاپ رو لیست کن", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertFalse(plan.index_only)

    def test_exact_fast_command_is_never_triaged(self):
        plan = _agent().plan("ساعت چنده", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertFalse(plan.index_only)
        self.assertIsNotNone(plan.fast_call)

    def test_web_gate_recognizes_price_lookup_without_explicit_web_word(self):
        self.assertIn("web", protocol.detect_categories("قیمت یورو رو پیدا کن"))
        self.assertIn("web", protocol.detect_categories("نرخ دلار چنده؟"))
        self.assertIn("web", protocol.detect_categories("قیمت طلا رو از اینترنت بررسی کن"))

    def test_english_task_intents_cover_common_pc_and_web_workflows(self):
        cases = (
            ("Prepare a report using three official sources comparing Windows 11 and Linux", {"system", "web"}),
            ("Check available space on drive C. If below 10 GB, find largest files in Downloads", {"system", "files"}),
            ("Open Chrome, navigate to the provided webpage, and summarize its three main points", {"apps", "web"}),
            ("Sort PDFs in the project folder by date and move files older than one year into Archive", {"files", "time"}),
            ("If Discord is not running, launch it. Then switch audio output to Bluetooth headphones", {"apps", "audio", "bluetooth"}),
            ("Find the latest Python version online and provide the official download link", {"web"}),
            ("Create an Excel spreadsheet with prices of five laptops suitable for programming and save to Desktop", {"apps", "files", "web"}),
            ("Read the article at the link I provide and verify its claims against official sources", {"web"}),
            ("Change the default microphone and document the result in Notepad", {"apps", "audio", "desktop"}),
            ("If the config file exists, back it up, then change timeout to 30", {"files"}),
            ("Identify applications consuming the most RAM; report only, do not close them", {"apps", "system"}),
            ("Find a 4K Porsche wallpaper, download it, and apply it using Wallpaper Engine", {"apps", "files", "web"}),
            ("Check Wi-Fi; if disconnected, reconnect", {"system"}),
            ("Back up the Pictures folder to drive D and report the copied file count", {"files"}),
            ("Write a professional email explaining the project delay; show me the draft for approval before sending", set()),
            ("Compare three online component retailers and find the cheapest 1 TB SSD", {"web"}),
            ("If the application installer exists in Downloads, run it; otherwise find the official website", {"apps", "files", "web"}),
            ("Open Windows Settings, navigate to Bluetooth, and report paired device names", {"apps", "bluetooth", "desktop"}),
            ("Check the battery; if below 20%, enable Battery Saver", {"system"}),
            ("Find duplicate files, list only confirmed duplicates, and ask permission before deleting", {"files"}),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertTrue(expected.issubset(protocol.detect_categories(prompt)))

    def test_web_price_queries_do_not_fall_into_time_or_system(self):
        cases = (
            "قیمت یورو رو پیدا کن",
            "نرخ دلار چنده؟",
            "نرخ دلار امروز چنده؟",
            "قیمت طلا رو از اینترنت بررسی کن",
        )
        for prompt in cases:
            with self.subTest(prompt=prompt):
                categories = protocol.detect_categories(prompt)
                self.assertIn("web", categories)
                self.assertNotIn("time", categories)
                self.assertNotIn("system", categories)

    def test_web_article_summary_is_not_a_local_file_request(self):
        for prompt in ("یک مقاله رو بخون و خلاصه کن", "خلاصه یک مقاله درباره Passkey رو پیدا کن"):
            with self.subTest(prompt=prompt):
                categories = protocol.detect_categories(prompt)
                self.assertIn("web", categories)
                self.assertNotIn("files", categories)

    def test_network_diagnostics_remain_system_requests(self):
        categories = protocol.detect_categories("وضعیت اتصال اینترنت رو بررسی کن")
        self.assertIn("system", categories)

    def test_resume_preserves_failure_signatures(self):
        agent = _agent()
        agent.tasks = SimpleNamespace(save=lambda: None)
        signatures = {"open_app:{name:missing}": 1}
        plan = SimpleNamespace(
            steps=[], fail_sigs=signatures, status="paused", question="continue", updated=0,
        )
        agent._prepare_resume(plan)
        self.assertIs(plan.fail_sigs, signatures)
        self.assertEqual(plan.status, P_RUNNING)
        self.assertEqual(plan.question, "")

    def test_competitive_safe_chat_has_no_tool_plan(self):
        agent = _agent()
        agent._competitive_safe_mode = True
        self.assertIsNone(agent.plan("سلام، حالت چطوره؟", session_id="kira"))

    def test_triage_prompt_is_a_small_fraction_of_the_full_catalog(self):
        agent = _agent()
        plan = agent.plan("سلام", session_id="kira")
        small = agent.tools_block(plan)
        plan.index_only = False
        full = agent.tools_block(plan)
        self.assertLess(len(small), len(full) / 2)
        self.assertIn("use_tools", small)
        self.assertNotIn("DESKTOP RULES", small)


class TriageRunTests(unittest.TestCase):
    def test_chat_turn_is_one_small_model_call(self):
        agent = _agent()
        plan = agent.plan("سلام، حالت چطوره؟", session_id="kira")
        router = _ScriptedRouter("سلام! خوبم، تو چطوری؟")
        out = []
        result = agent.run(router, [{"role": "user", "content": "سلام، حالت چطوره؟"}], "SYS", 0.7, plan, on_chunk=out.append)
        self.assertEqual(len(router.prompts), 1)
        self.assertIn("CAPABILITY INDEX", router.prompts[0])
        self.assertEqual(result["text"], "سلام! خوبم، تو چطوری؟")
        self.assertNotIn("_escalate", result)
        self.assertEqual("".join(out), result["text"])

    def test_chat_turn_does_not_take_the_web_research_lock(self):
        agent = _agent()
        plan = agent.plan("سلام", session_id="kira")
        self.assertTrue(agent._web_research_lock.acquire(blocking=False))     # held by "another character"
        try:
            router = _ScriptedRouter("سلام!")
            done = []
            t = threading.Thread(target=lambda: done.append(
                agent.run(router, [{"role": "user", "content": "سلام"}], "SYS", 0.7, plan, on_chunk=lambda s: None)))
            t.start()
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), "a chat turn must not wait for another character's web research")
        finally:
            agent._web_research_lock.release()

    def test_model_asking_for_the_pc_escalates_without_showing_the_block(self):
        agent = _agent()
        plan = agent.plan("یه والپیپر زنده‌ی پورشه بذار برام", session_id="kira")
        router = _ScriptedRouter(USE_TOOLS_REPLY, "برنامه را بررسی کردم.")
        out = []
        result = agent.run(router, [{"role": "user", "content": "x"}], "SYS", 0.7, plan, on_chunk=out.append)
        self.assertEqual(len(router.prompts), 2)
        self.assertIn("CAPABILITY INDEX", router.prompts[0])
        self.assertNotIn("CAPABILITY INDEX", router.prompts[1])
        self.assertIn("PC TOOLS", router.prompts[1])
        self.assertGreater(len(router.prompts[1]), len(router.prompts[0]) * 2)
        self.assertNotIn("use_tools", "".join(out))                              # the user never sees the internal block
        self.assertEqual(result["text"], "برنامه را بررسی کردم.")
        self.assertNotIn("_escalate", result)
        self.assertFalse(plan.index_only)

    def test_escalation_uses_the_planner_when_planning_is_enabled(self):
        agent = _agent()
        plan = agent.plan("یه والپیپر زنده‌ی پورشه بذار برام", session_id="kira")
        calls = []
        agent.planning_enabled = lambda: True
        agent.run_planned = lambda *a, **k: calls.append(a[4]) or {"text": "planned", "stopped": False}
        router = _ScriptedRouter(USE_TOOLS_REPLY)
        result = agent.run(router, [{"role": "user", "content": "x"}], "SYS", 0.7, plan, on_chunk=lambda s: None)
        self.assertEqual(result["text"], "planned")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].complex)
        self.assertNotIn("mcp", calls[0].categories)                              # external tools stay opt-in

    def test_a_direct_tool_block_in_the_triage_round_also_escalates(self):
        agent = _agent()
        plan = agent.plan("سلام", session_id="kira")
        router = _ScriptedRouter('<kira_tool>{"tool": "open_app", "args": {"name": "x"}}</kira_tool>', "ok")
        result = agent.run(router, [{"role": "user", "content": "سلام"}], "SYS", 0.7, plan, on_chunk=lambda s: None)
        self.assertEqual(len(router.prompts), 2)                                   # never executed from the triage round
        self.assertEqual(result["tools"], [])

    def test_index_lists_every_local_group_but_not_external_tools(self):
        index = protocol.build_index(_agent().registry.all())
        for group in ("system", "files", "apps", "desktop", "web"):
            self.assertIn(f"- {group} (", index)
        self.assertNotIn("mcp", index)


if __name__ == "__main__":
    unittest.main()
