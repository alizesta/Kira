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
    agent.registry.execution_guard = agent._game_mode_execution_guard
    agent._pending_by_session = {}
    agent._pending_new_sessions = set()
    agent._init_session_turn_states()
    return agent


class _NativeSchemaRouter:
    def __init__(self, text="done"):
        self.text = text
        self.schemas = None
        self.prompts = []
        self.native_calls = 0
        self.stream_calls = 0

    def chat_with_tools(self, messages, system_prompt, temperature, schemas, on_event=None):
        self.native_calls += 1
        self.schemas = list(schemas)
        self.prompts.append(system_prompt)
        return {"text": self.text, "tool_calls": [], "stopped": False}

    def chat_stream(self, messages, system_prompt, temperature, on_chunk=None, on_event=None, retry_index=0, **_):
        self.stream_calls += 1
        self.prompts.append(system_prompt)
        if on_chunk:
            on_chunk(self.text)
        return {"text": self.text, "stopped": False, "interrupted": None}


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

    def test_unknown_actionable_request_keeps_compact_triage(self):
        prompt = "یه قابلیت ناشناخته رو برام اعمال کن"
        self.assertTrue(protocol.is_actionable_intent(prompt))
        self.assertFalse(protocol.detect_categories(prompt))
        plan = _agent().plan(prompt, session_id="unknown-action")
        self.assertIsNotNone(plan)
        self.assertTrue(plan.index_only)
        self.assertEqual(plan.schema_categories, set())

    def test_wallpaper_setup_detects_the_mixed_workflow_domains(self):
        prompt = "یه والپیپر زنده‌ی پورشه بذار برام"
        self.assertTrue(protocol.is_actionable_intent(prompt))
        categories = protocol.detect_categories(prompt)
        self.assertTrue({"apps", "files", "web"}.issubset(categories))
        plan = _agent().plan(prompt, session_id="wallpaper-setup")
        self.assertFalse(plan.index_only)
        self.assertTrue({"apps", "files", "web"}.issubset(plan.schema_categories))

    def test_polite_offer_for_help_is_not_an_actionable_pc_request(self):
        self.assertFalse(protocol.is_actionable_intent("سلام، می‌تونی کمکم کنی؟"))

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
        agent = _agent()
        for index, (prompt, expected) in enumerate(cases, 1):
            with self.subTest(prompt=prompt):
                detected = protocol.detect_categories(prompt)
                self.assertTrue(expected.issubset(detected))
                plan = agent.plan(prompt, session_id=f"english-{index}")
                self.assertIsNotNone(plan)
                self.assertEqual(plan.index_only, not bool(detected))

    def test_generic_source_code_discussion_is_not_misclassified_as_web(self):
        categories = protocol.detect_categories("Explain how source code is compiled")
        self.assertNotIn("web", categories)
        plan = _agent().plan("Explain how source code is compiled", session_id="source-code-chat")
        self.assertTrue(plan.index_only)

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

    def test_auto_plan_keeps_security_categories_but_selects_topic_schemas(self):
        agent = _agent()
        plan = agent.plan("فایل‌های PDF قدیمی‌تر از یک ماه رو پیدا کن و فهرست کن", session_id="files-only")
        self.assertIsNotNone(plan)
        self.assertFalse(plan.index_only)
        self.assertEqual(plan.schema_categories, {"files"})
        self.assertIn("system", plan.categories)       # full availability/safety scope is unchanged
        self.assertIn("apps", plan.categories)
        selected = agent.registry.schemas_for_selected_categories(plan.schema_categories)
        all_schemas = agent.registry.schemas()
        selected_names = {item["name"] for item in selected}
        self.assertIn("search_files", selected_names)
        self.assertNotIn("bluetooth_status", selected_names)
        self.assertNotIn("web_search", selected_names)
        self.assertLess(len(selected), len(all_schemas) / 2)

    def test_native_function_call_receives_only_selected_topic_schemas(self):
        agent = _agent(agent_planning="off")
        plan = agent.plan("فایل‌های PDF قدیمی‌تر از یک ماه رو پیدا کن و فهرست کن", session_id="native-files")
        router = _NativeSchemaRouter()
        result = agent.run(
            router,
            [{"role": "user", "content": "فایل‌های PDF قدیمی‌تر از یک ماه رو پیدا کن و فهرست کن"}],
            "SYS", 0.2, plan,
        )
        self.assertEqual(result["text"], "done")
        self.assertEqual(router.native_calls, 1)
        self.assertEqual(router.stream_calls, 0)
        names = {item["name"] for item in router.schemas}
        self.assertIn("search_files", names)
        self.assertNotIn("bluetooth_status", names)
        self.assertNotIn("web_search", names)

    def test_mixed_request_keeps_all_detected_topic_schema_groups(self):
        agent = _agent()
        prompt = "Open Windows Settings, navigate to Bluetooth, and inspect paired devices."
        plan = agent.plan(prompt, session_id="mixed-desktop-bluetooth")
        self.assertIsNotNone(plan)
        self.assertTrue({"apps", "desktop", "bluetooth"}.issubset(plan.schema_categories))
        names = {item["name"] for item in agent.registry.schemas_for_selected_categories(plan.schema_categories)}
        self.assertIn("bluetooth_status", names)
        self.assertNotIn("web_search", names)

    def test_always_mode_retains_the_full_explicit_tool_catalog(self):
        agent = _agent(tools_mode="always")
        plan = agent.plan("سلام", session_id="always-mode")
        self.assertEqual(plan.schema_categories, set(protocol.ALL_CATEGORIES))
        self.assertEqual(
            len(agent.registry.schemas_for_selected_categories(plan.schema_categories)),
            len(agent.registry.schemas()),
        )

    def test_native_route_does_not_bypass_compact_triage_for_unknown_chat(self):
        agent = _agent(agent_planning="off")
        prompt = "می‌تونی یه کم کمکم کنی؟"
        plan = agent.plan(prompt, session_id="unknown-chat")
        self.assertTrue(plan.index_only)
        router = _NativeSchemaRouter(text="حتماً، بگو چه کمکی لازم داری؟")
        result = agent.run(router, [{"role": "user", "content": prompt}], "SYS", 0.2, plan)
        self.assertEqual(result["text"], router.text)
        self.assertEqual(router.native_calls, 0)
        self.assertEqual(router.stream_calls, 1)
        self.assertIn("CAPABILITY INDEX", router.prompts[0])

    def test_off_scope_tool_call_is_journaled_and_handler_never_runs(self):
        from kira.tools.registry import Tool, READ

        agent = _agent()
        handler_calls = []
        agent.registry.register(Tool(
            "scope_probe", "test-only tool outside the selected category",
            lambda args: handler_calls.append(args) or "executed",
            (), READ, ("bluetooth",),
        ))
        scope_token = agent._active_schema_scope.set({"files"})
        try:
            with agent._use_session("files-scope"):
                results = agent._run_calls([{"tool": "scope_probe", "args": {}}], [], None)
        finally:
            agent._active_schema_scope.reset(scope_token)
        self.assertEqual(handler_calls, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "denied")
        self.assertIn("دامنه", results[0].text)
        records = agent.registry.access.journal.recent(10)
        self.assertTrue(any(item.get("tool") == "scope_probe" and item.get("status") == "denied" for item in records))

    def test_empty_selected_schema_scope_never_means_all_tools(self):
        agent = _agent()
        self.assertEqual(agent.registry.schemas_for_selected_categories(set()), [])
        self.assertEqual(agent.registry.catalog_for_selected_categories(set()), "")

    def test_triage_prompt_is_a_small_fraction_of_the_full_catalog(self):
        agent = _agent()
        plan = agent.plan("سلام", session_id="kira")
        small = agent.tools_block(plan)
        plan.index_only = False
        plan.schema_categories = set(plan.categories) - {"mcp", "agents"}  # the explicit triage escalation broadens only now
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
