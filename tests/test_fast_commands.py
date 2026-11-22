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

    def test_competitive_safe_ordinary_chat_gets_no_tool_plan(self):
        agent = self._agent(tool_name="get_system_info")
        agent._competitive_safe_mode = True
        self.assertIsNone(agent.plan("سلام، حالت چطوره؟", session_id="kira"))

    def test_competitive_safe_keeps_explicit_web_request(self):
        agent = self._agent(tool_name="get_system_info")
        agent._competitive_safe_mode = True
        plan = agent.plan("در وب درباره پورشه 911 تحقیق کن", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.categories, {"web"})            # local categories stay blocked

    def test_tool_failure_is_reported_without_false_success(self):
        from kira.tools.registry import ERROR
        agent = self._agent(ERROR)
        plan = agent.plan("صدا رو روی ۵۰ درصد بذار", session_id="kira")
        result = agent.run(_NoModelRouter(), [{"role": "user", "content": "صدا رو روی ۵۰ درصد بذار"}],
                           "system", 0.2, plan)
        self.assertIn("❌", result["text"])
        self.assertNotIn("✅", result["text"])
        self.assertIn("Windows audio endpoint unavailable", result["text"])

    def test_fast_path_does_not_override_complex_planner_decision(self):
        from kira.tools.agent import ToolPlan
        agent = self._agent()
        agent.decide = lambda text, base: ToolPlan({"audio"}, complex=True)
        plan = agent.plan("صدا رو روی ۵۰ درصد بذار", session_id="kira")
        self.assertTrue(plan.complex)
        self.assertIsNone(plan.fast_call)

    def test_fast_path_rejects_sensitive_registry_tool(self):
        agent = self._agent(tool_name="get_system_info")
        agent.registry.get("get_system_info").level = 3
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.fast_call)

    def test_fast_path_rejects_external_registry_tool(self):
        agent = self._agent(tool_name="get_system_info")
        agent.registry.get("get_system_info").external = True
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.fast_call)

    def test_fast_path_rejects_registry_category_mismatch(self):
        agent = self._agent(tool_name="get_system_info")
        agent.registry.get("get_system_info").categories = ("files",)
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.fast_call)

    def test_fast_path_respects_tools_disabled(self):
        agent = self._agent(tool_name="get_system_info")
        agent.settings["tools_mode"] = "off"
        self.assertIsNone(agent.plan("مشخصات سیستم چیه", session_id="kira"))

    def test_fast_path_requires_registered_tool(self):
        agent = self._agent(tool_name="get_system_info")
        del agent.registry.tools["get_system_info"]
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.fast_call)



class FastPathRealRegistryBoundaryTests(unittest.TestCase):
    """Exercise the Fast Path through the production ToolRegistry permission boundary."""

    def _agent(self):
        from kira.tools.agent import ToolAgent
        from kira.tools.registry import Tool, ToolRegistry, READ

        registry = ToolRegistry()
        calls = []
        registry.register(Tool(
            "get_system_info",
            "test-only system information reader",
            lambda args: calls.append(dict(args)) or "system facts",
            (),
            READ,
            ("system",),
        ))

        agent = ToolAgent.__new__(ToolAgent)
        agent.settings = {"tools_mode": "auto", "agent_planning": "off"}
        agent.registry = registry
        agent._competitive_safe_mode = False
        agent._pending_by_session = {}
        agent._pending_new_sessions = set()
        agent._init_session_turn_states()
        registry.execution_guard = agent._game_mode_execution_guard
        registry.access.require_grants = True
        return agent, registry, calls

    def _plan(self, agent):
        plan = agent.plan("مشخصات سیستم چیه", session_id="kira")
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan.fast_call,
            {"tool": "get_system_info", "args": {}, "category": "system"},
        )
        return plan

    def _run(self, agent, plan):
        return agent.run(
            _NoModelRouter(),
            [{"role": "user", "content": "مشخصات سیستم چیه"}],
            "system",
            0.2,
            plan,
        )

    def test_fast_path_executes_through_real_registry(self):
        agent, registry, calls = self._agent()
        plan = self._plan(agent)
        result = self._run(agent, plan)

        self.assertTrue(result["fast_path"])
        self.assertEqual(result["tools"][0]["status"], "ok")
        self.assertIn("system facts", result["text"])
        self.assertEqual(calls, [{}])
        self.assertEqual(registry.access.journal.recent()[-1]["status"], "ok")

    def test_tools_mode_change_after_planning_is_enforced_at_execution(self):
        from kira.tools.registry import DENIED

        agent, _registry, calls = self._agent()
        plan = self._plan(agent)
        agent.settings["tools_mode"] = "off"
        result = self._run(agent, plan)

        self.assertEqual(calls, [])
        self.assertEqual(result["tools"][0]["status"], DENIED)
        self.assertIn("ابزارها خاموش", result["text"])

    def test_competitive_safe_transition_cancels_pending_fast_call(self):
        agent, _registry, calls = self._agent()
        plan = self._plan(agent)
        agent.set_competitive_safe_mode(True)
        result = self._run(agent, plan)

        self.assertEqual(calls, [])
        self.assertTrue(result["stopped"])
        self.assertEqual(result["tools"], [])

    def test_competitive_safe_execution_guard_denies_fast_call(self):
        from kira.tools.registry import DENIED

        agent, _registry, calls = self._agent()
        plan = self._plan(agent)
        # Exercise the registry's defence-in-depth guard independently of
        # the public transition method's immediate cancellation.
        agent._competitive_safe_mode = True
        result = self._run(agent, plan)

        self.assertEqual(calls, [])
        self.assertEqual(result["tools"][0]["status"], DENIED)
        self.assertIn("Competitive Safe", result["text"])

    def test_same_fast_call_is_not_executed_twice_in_one_turn(self):
        agent, _registry, calls = self._agent()
        plan = self._plan(agent)
        first = self._run(agent, plan)
        second = self._run(agent, plan)

        self.assertEqual(calls, [{}])
        self.assertEqual(first["tools"][0]["status"], "ok")
        self.assertTrue(second["tools"][0]["cached"])



class SemanticPlannerRoutingTests(unittest.TestCase):
    def _autonomy_probe(self):
        from kira.tools.autonomy import AutonomyMixin

        class Probe(AutonomyMixin):
            def __init__(self):
                self.settings = {"agent_planning": "auto"}
                self._turn_session_id = "kira"
                self._resume_sessions = set()
                self.tasks = SimpleNamespace(active=lambda _owner: None)

            def planning_enabled(self):
                return True

            def _remember_task_preference(self, _text):
                return None

        return Probe()

    def test_legacy_task_schema_gets_goal_based_review_criteria(self):
        from kira.tools.tasks import TaskPlan

        legacy = TaskPlan.from_dict({
            "id": "legacy",
            "goal": "open Wallpaper Engine and apply the selected wallpaper",
            "steps": [{"id": 1, "title": "Open app", "tool": "open_app", "status": "done"}],
        })
        self.assertEqual(legacy.success_criteria, [legacy.goal])
        self.assertEqual(legacy.steps[0].postcondition, legacy.goal)

    def test_one_tool_request_still_uses_model_to_define_its_goal(self):
        from kira.tools.agent import ToolPlan

        probe = self._autonomy_probe()
        plan = probe.decide("از بین برنامه‌های نصب‌شده نسخه‌ی Discord را پیدا کن", ToolPlan({"apps"}))
        self.assertTrue(plan.complex)
        self.assertIn("Planner", " ".join(plan.reasons))

    def test_natural_task_is_routed_to_model_without_verb_matching(self):
        from kira.tools.agent import ToolPlan

        probe = self._autonomy_probe()
        base = ToolPlan({"apps"})
        plan = probe.decide("والپیپر انجین رو باز کن، یک طرح مناسب پورشه پیدا کن و اعمالش کن", base)
        self.assertTrue(plan.complex)
        self.assertIn("Planner", " ".join(plan.reasons))

    def test_explicit_external_tool_intent_is_not_silently_filtered_from_catalog(self):
        from kira.tools.agent import ToolAgent, ToolPlan

        class Registry:
            web_context = None
            def catalog(self, categories):
                return ",".join(sorted(categories))
        agent = ToolAgent.__new__(ToolAgent)
        agent.registry = Registry()
        agent._competitive_safe_mode = False
        agent._memo_block = lambda: ""
        plan = ToolPlan({"apps", "mcp", "agents"}, complex=True)
        block = agent.tools_block(plan)
        self.assertIn("mcp", block)
        self.assertIn("agents", block)

    def test_exact_fast_command_keeps_deterministic_fast_path(self):
        from kira.tools.agent import ToolPlan

        probe = self._autonomy_probe()
        base = ToolPlan({"apps"})
        plan = probe.decide("کروم رو باز کن", base)
        self.assertFalse(plan.complex)

    def test_auto_mode_lets_model_classify_unknown_intent_without_category_keywords(self):
        from kira.tools.agent import ToolAgent

        agent = ToolAgent.__new__(ToolAgent)
        agent.settings = {"tools_mode": "auto"}
        agent.registry = SimpleNamespace(web_context=None)
        plan = agent._plan_simple("میشه این کار رو برام انجام بدی؟")
        self.assertIsNotNone(plan)
        self.assertIn("desktop", plan.categories)
        self.assertIn("files", plan.categories)
        self.assertNotIn("mcp", plan.categories)
        self.assertNotIn("agents", plan.categories)
        self.assertIn("web", plan.categories)
        # No known task signal: the model triages with a short capability index first (cheap for chat),
        # and only escalates to the planner when it asks for the PC (see tests/test_task_triage.py).
        self.assertTrue(plan.index_only)
        decision = self._autonomy_probe().decide("میشه این کار رو برام انجام بدی؟", plan)
        self.assertFalse(decision.complex)

    def test_no_base_tool_plan_remains_plain_chat_for_direct_decision(self):
        probe = self._autonomy_probe()
        self.assertIsNone(probe.decide("سلام، حالت چطوره؟", None))


class SemanticResultReviewTests(unittest.TestCase):
    def _step(self, data="پنجره فعال: Wallpaper Engine", sid=1):
        from kira.tools.tasks import Step, REVIEW
        step = Step(sid, "رسیدن به وضعیت درخواستی", "window_active", status=REVIEW)
        step.data = data
        return step

    def test_review_requires_exact_evidence_for_satisfied_verdict(self):
        from kira.tools.planner import parse_review

        raw = ('<kira_review>{"reviews":[{"step":1,"verdict":"satisfied",'
               '"reason":"پنجره‌ی موردنظر فعال است","evidence":"پنجره فعال: Wallpaper Engine"}]}</kira_review>')
        parsed = parse_review(raw, [self._step()])
        self.assertEqual(parsed[0]["verdict"], "satisfied")

    def test_review_rejects_hallucinated_evidence(self):
        from kira.tools.planner import parse_review

        raw = ('<kira_review>{"reviews":[{"step":1,"verdict":"satisfied",'
               '"reason":"انجام شد","evidence":"Wallpaper Engine is fully configured"}]}</kira_review>')
        with self.assertRaises(ValueError):
            parse_review(raw, [self._step()])

    def test_review_requires_every_pending_step_exactly_once(self):
        from kira.tools.planner import parse_review

        raw = ('<kira_review>{"reviews":[{"step":1,"verdict":"uncertain",'
               '"reason":"خروجی فقط ارسال کلیک را تأیید می‌کند"}]}</kira_review>')
        with self.assertRaises(ValueError):
            parse_review(raw, [self._step(), self._step("نتیجه دوم", sid=2)])

    def test_read_only_result_can_be_observed_again(self):
        from kira.tools.autonomy import AutonomyMixin
        from kira.tools.registry import ToolResult, OK
        from kira.tools.tasks import Step, TaskPlan, REVIEW

        plan = TaskPlan("t-read", "مشاهده وضعیت پنجره")
        step = Step(1, "خواندن وضعیت", "window_active")
        plan.steps.append(step)
        result = ToolResult("window_active", OK, "پنجره فعال: Wallpaper Engine", {}, 1)

        class Probe(AutonomyMixin):
            pass

        Probe()._settle_step(plan, step, result, "read-signature", object)
        self.assertEqual(step.status, REVIEW)
        self.assertNotIn("read-signature", plan.done_sigs)

    def test_single_tool_plan_uses_goal_as_legacy_success_criterion(self):
        from kira.tools.planner import parse_plan

        class Registry:
            def get(self, name):
                return SimpleNamespace(level=1) if name == "get_system_info" else None

        raw = ('<kira_plan>{"goal":"read the current system information",'
               '"steps":[{"id":1,"title":"Read system information","tool":"get_system_info",'
               '"depends_on":[],"confirm":false}]}'
               '</kira_plan>')
        draft = parse_plan(raw, Registry(), 8)
        self.assertEqual(draft["success_criteria"], ["read the current system information"])
        self.assertEqual(draft["steps"][0]["postcondition"], "read the current system information")

    def test_plan_parser_preserves_goal_and_step_success_conditions(self):
        from kira.tools.planner import parse_plan
        from kira.tools.tasks import TaskPlan

        class Registry:
            def get(self, name):
                return SimpleNamespace(level=1) if name == "window_active" else None

        raw = ('<kira_plan>{"goal":"activate Wallpaper Engine",'
               '"success_criteria":["Wallpaper Engine is the active window"],'
               '"steps":[{"id":1,"title":"Read active window","postcondition":"Wallpaper Engine is active",'
               '"tool":"window_active","depends_on":[],"confirm":false}]}'
               '</kira_plan>')
        draft = parse_plan(raw, Registry(), 8)
        plan = TaskPlan("t-criteria", draft["goal"])
        plan.apply_draft(draft)
        self.assertEqual(plan.success_criteria, ["Wallpaper Engine is the active window"])
        self.assertEqual(plan.steps[0].postcondition, "Wallpaper Engine is active")
        self.assertIn("FINAL SUCCESS CRITERIA", plan.render_state())
        self.assertIn("postcondition: Wallpaper Engine is active", plan.render_state())

    def test_goal_review_requires_exact_evidence_for_every_criterion(self):
        from kira.tools.planner import parse_review
        from kira.tools.tasks import Step

        goal = Step(0, "final goal review", postcondition="app is active\nwallpaper is applied")
        goal.data = "Active window: Wallpaper Engine\nApplied wallpaper: Porsche 911"
        one_quote = ('<kira_review>{"reviews":[{"step":0,"verdict":"satisfied",'
                     '"reason":"both are done","evidence":[{"criterion":1,"quote":"Active window: Wallpaper Engine"}]}]}'
                     '</kira_review>')
        with self.assertRaises(ValueError):
            parse_review(one_quote, [goal])
        two_quotes = ('<kira_review>{"reviews":[{"step":0,"verdict":"satisfied",'
                      '"reason":"both criteria are proven","evidence":[{"criterion":1,"quote":"Active window: Wallpaper Engine"},'
                      '{"criterion":2,"quote":"Applied wallpaper: Porsche 911"}]}]}'
                      '</kira_review>')
        result = parse_review(two_quotes, [goal])
        self.assertEqual(result[0]["verdict"], "satisfied")
        self.assertEqual(len(result[0]["evidence"]), 2)

    def test_report_only_task_does_not_wait_for_tool_evidence(self):
        from kira.tools.autonomy import AutonomyMixin
        from kira.tools.tasks import TaskPlan, Step, P_DONE

        class Probe(AutonomyMixin):
            def __init__(self):
                self._pending_by_session = {}

        plan = TaskPlan("t-report", "explain the result")
        plan.success_criteria = ["a clear explanation is provided"]
        plan.steps.append(Step(1, "Write the explanation"))
        Probe()._settle_plan(plan)
        self.assertEqual(plan.status, P_DONE)

    def test_task_cannot_be_marked_done_without_final_goal_review(self):
        from kira.tools.autonomy import AutonomyMixin
        from kira.tools.tasks import TaskPlan, Step, DONE, P_PAUSED

        class Probe(AutonomyMixin):
            def __init__(self):
                self._pending_by_session = {}

        plan = TaskPlan("t-final", "complete the requested UI task")
        plan.success_criteria = ["the requested wallpaper is applied"]
        plan.steps.append(Step(1, "apply wallpaper", "ui_click", status=DONE))
        Probe()._settle_plan(plan)
        self.assertEqual(plan.status, P_PAUSED)
        self.assertFalse(plan.goal_verified)

    def test_agent_gate_hides_review_blocks(self):
        from kira.tools.planner import AgentGate

        shown = []
        gate = AgentGate(shown.append)
        gate.feed('<kira_review>{"reviews":[]}</kira_review>')
        gate.finish()
        self.assertTrue(gate.is_review)
        self.assertEqual(shown, [])

    def test_action_result_is_locked_against_blind_repetition_until_review(self):
        from kira.tools.autonomy import AutonomyMixin
        from kira.tools.registry import ToolResult, OK
        from kira.tools.tasks import Step, TaskPlan, REVIEW

        plan = TaskPlan("t-test", "هدف کاربر")
        step = Step(1, "فعال‌کردن پنجره", "window_focus", postcondition="پنجره Wallpaper Engine فعال باشد")
        plan.steps.append(step)
        result = ToolResult("window_focus", OK, "پنجره موردنظر فعال شد", {}, 2)

        class Probe(AutonomyMixin):
            pass

        note = Probe()._settle_step(plan, step, result, "call-signature", object)
        self.assertEqual(step.status, REVIEW)
        self.assertIn("NOT established", note)
        self.assertIn("call-signature", plan.done_sigs)
        self.assertIn("ارزیابی تحقق هدف", plan.done_sigs["call-signature"])
        self.assertEqual(step.postcondition, "پنجره Wallpaper Engine فعال باشد")

if __name__ == "__main__":
    unittest.main()
