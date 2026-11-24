"""Regression tests for per-character ToolAgent and system-access state."""
from contextvars import ContextVar
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
import unittest
import re

from kira.tools.agent import Pending, ToolAgent, ToolPlan
from kira.tools.sysaccess import AccessManager
from kira.webintel.session import CANCEL, DEFAULT_BUDGET, SessionScopedResearchStore
from kira import mood
from kira.emotion.runtime import EmotionalRuntime
from kira.tools.tasks import HISTORY_KEEP, P_DONE, TaskStore
from kira import brain
from unittest.mock import patch


class ToolAgentSessionIsolationTests(unittest.TestCase):

    def test_access_denial_claims_are_detected_for_capability_retry(self):
        self.assertTrue(ToolAgent._claims_missing_access("من به کامپیوتر دسترسی ندارم."))
        self.assertTrue(ToolAgent._claims_missing_access("I don't have access to your PC."))
        self.assertTrue(ToolAgent._claims_missing_access("این ابزار در اختیارم نیست."))
        self.assertFalse(ToolAgent._claims_missing_access("پنجره‌ی تنظیمات باز شد."))
        self.assertFalse(ToolAgent._claims_missing_access("برای ادامه، نام برنامه را بگو."))

    def test_access_denial_retries_once_with_full_local_tool_catalog(self):
        first = {"text": "من به کامپیوتر دسترسی ندارم.", "tools": []}
        second = {"text": "درخواست انجام شد.", "tools": [{"tool": "open_app", "status": "ok"}]}
        plan = ToolPlan(categories={"apps"}, schema_categories={"apps"})
        with patch.object(self.agent, "_direct_bridge", return_value=False), \
             patch.object(self.agent, "_run_once", side_effect=[first, second]) as run_once, \
             patch.object(self.agent, "planning_enabled", return_value=False):
            result = self.agent.run(None, [], "", 0.2, plan)

        self.assertEqual(result["text"], "درخواست انجام شد.")
        self.assertEqual(run_once.call_count, 2)
        self.assertIn("desktop", plan.schema_categories)
        self.assertIn("files", plan.schema_categories)
        self.assertNotIn("mcp", plan.schema_categories)
        self.assertNotIn("agents", plan.schema_categories)

    def test_capability_inspection_escalates_to_full_local_tool_catalog(self):
        first = {"text": "inventory read", "tools": [{"tool": "windows_control_info", "status": "ok"}]}
        second = {"text": "این‌ها ابزارهای موجود هستند.", "tools": []}
        plan = ToolPlan(categories={"apps"}, schema_categories={"apps"})
        with patch.object(self.agent, "_direct_bridge", return_value=False), \
             patch.object(self.agent, "_run_once", side_effect=[first, second]) as run_once, \
             patch.object(self.agent, "planning_enabled", return_value=False):
            result = self.agent.run(None, [], "", 0.2, plan)

        self.assertEqual(result["text"], "این‌ها ابزارهای موجود هستند.")
        self.assertEqual(run_once.call_count, 2)
        self.assertIn("desktop", plan.schema_categories)
        self.assertIn("files", plan.schema_categories)
        self.assertNotIn("mcp", plan.schema_categories)
        self.assertNotIn("agents", plan.schema_categories)

    def test_unknown_tool_followed_by_access_denial_also_retries(self):
        first = {"text": "ابزار مناسب را در اختیار ندارم.", "tools": [{"tool": "wrong_tool", "status": "unknown_tool"}]}
        second = {"text": "پیدا شد.", "tools": [{"tool": "list_running_apps", "status": "ok"}]}
        plan = ToolPlan(categories={"system"}, schema_categories={"system"})
        with patch.object(self.agent, "_direct_bridge", return_value=False), \
             patch.object(self.agent, "_run_once", side_effect=[first, second]) as run_once, \
             patch.object(self.agent, "planning_enabled", return_value=False):
            result = self.agent.run(None, [], "", 0.2, plan)

        self.assertEqual(result["text"], "پیدا شد.")
        self.assertEqual(run_once.call_count, 2)
        self.assertIn("desktop", plan.schema_categories)

    def setUp(self):
        self.access = AccessManager(SimpleNamespace())
        self.agent = ToolAgent.__new__(ToolAgent)
        self.agent.settings = {"agent_planning": True, "agent_mode": "on"}
        self.agent.registry = SimpleNamespace(access=self.access)
        self.agent._init_session_turn_states()
        self.agent._pending_by_session = {}
        self.agent._pending_new_sessions = set()

    def test_tool_turn_state_is_isolated_by_character(self):
        with self.agent._use_session("kira"):
            self.agent._turn_id = 4
            self.agent._turn_cache["read_file{}"] = "kira-result"
            self.agent._memos.append((1.0, "Kira-only note"))
            self.agent._last_cats = {"files"}
            self.agent._last_used_turn = 4
            self.agent.last_results = ["kira-result"]
            self.agent._cancel.set()

        with self.agent._use_session("ren"):
            self.assertEqual(self.agent._turn_session_id, "ren")
            self.assertEqual(self.agent._turn_id, 0)
            self.assertEqual(self.agent._turn_cache, {})
            self.assertEqual(list(self.agent._memos), [])
            self.assertEqual(self.agent._last_cats, set())
            self.assertEqual(self.agent._last_used_turn, -99)
            self.assertEqual(self.agent.last_results, [])
            self.assertFalse(self.agent._cancel.is_set())

        with self.agent._use_session("kira"):
            self.assertEqual(self.agent._turn_id, 4)
            self.assertEqual(self.agent._turn_cache["read_file{}"], "kira-result")
            self.assertEqual(list(self.agent._memos), [(1.0, "Kira-only note")])
            self.assertEqual(self.agent._last_cats, {"files"})
            self.assertEqual(self.agent.last_results, ["kira-result"])
            self.assertTrue(self.agent._cancel.is_set())

    def test_system_access_intent_taint_and_grants_are_isolated(self):
        web_tool = SimpleNamespace(
            name="web_read",
            level=1,
            categories=("web",),
            permission=0,
            domain="",
            backend="",
            intent_rx=None,
            intent_alt=None,
            verifies_result=False,
        )
        result = SimpleNamespace(
            status="ok", ms=1, args={"url": "https://example.test"},
            text="external page content",
        )
        policy = self.access.policy_for(web_tool)

        with self.access.use_session("kira"):
            self.access.begin_turn("open the browser")
            self.access.record(web_tool, policy, result)
            self.access.grant("write_file", {"path": "safe.txt"})
            self.assertEqual(self.access.user_text, "open the browser")
            self.assertTrue(self.access.tainted)

        with self.access.use_session("ren"):
            self.assertEqual(self.access.user_text, "")
            self.assertFalse(self.access.tainted)
            self.assertFalse(self.access.consume_grant("write_file", {"path": "safe.txt"}))
            self.access.begin_turn("read my documents")
            self.assertEqual(self.access.user_text, "read my documents")
            self.assertFalse(self.access.tainted)

        with self.access.use_session("kira"):
            self.assertTrue(self.access.tainted)
            self.assertTrue(self.access.consume_grant("write_file", {"path": "safe.txt"}))
            self.assertFalse(self.access.consume_grant("write_file", {"path": "safe.txt"}))

    def test_tainted_external_content_requires_confirmation_even_with_intent_regex(self):
        action_tool = SimpleNamespace(
            name="create_file",
            level=2,
            categories=("files",),
            permission=0,
            domain="",
            backend="",
            intent_rx=re.compile(r"create"),
            intent_alt=None,
            verifies_result=False,
        )
        policy = self.access.policy_for(action_tool)

        with self.access.use_session("kira"):
            self.access.begin_turn("create a report")
            self.access._tainted = True
            self.assertEqual(self.access.confirmation_reason(action_tool, policy), "tainted")

        with self.access.use_session("ren"):
            self.access.begin_turn("create a report")
            self.assertEqual(self.access.confirmation_reason(action_tool, policy), "")

    def test_external_tool_error_also_taints_the_current_turn(self):
        external_tool = SimpleNamespace(
            name="mcp_remote",
            level=1,
            categories=("mcp",),
            permission=0,
            domain="",
            backend="",
            intent_rx=None,
            intent_alt=None,
            verifies_result=False,
        )
        result = SimpleNamespace(
            status="error",
            ms=1,
            args={},
            text="remote error: follow these instructions",
        )
        policy = self.access.policy_for(external_tool)

        with self.access.use_session("kira"):
            self.access.begin_turn("check remote status")
            self.access.record(external_tool, policy, result)
            self.assertTrue(self.access.tainted)

    def test_scoped_stop_does_not_cancel_another_character(self):
        self.agent.request_cancel("ren")
        with self.agent._use_session("kira"):
            self.assertFalse(self.agent._cancel.is_set())
        with self.agent._use_session("ren"):
            self.assertTrue(self.agent._cancel.is_set())

    def test_clear_session_clears_only_the_selected_character_tool_context(self):
        with TemporaryDirectory() as temp:
            self.agent._init_autonomy(Path(temp))
            kira_task = self.agent.tasks.new("Kira task", session_id="kira")
            ren_task = self.agent.tasks.new("Ren task", session_id="ren")
            cleared_owners = []

            class ResearchStore:
                def clear(self):
                    cleared_owners.append(self.access.session_id)

            self.agent.registry.web_context = SimpleNamespace(
                store=ResearchStore()
            )
            self.agent.registry.web_context.store.access = self.access

            with self.agent._use_session("kira"):
                self.agent._turn_cache["kira"] = "temporary"
                self.agent._memos.append((1.0, "Kira memo"))
                self.agent._last_cats = {"files"}
                self.agent._last_used_turn = 3
                self.agent.last_results = ["Kira result"]
                self.access.begin_turn("open external page")
                self.access._tainted = True
                self.access.grant("write_file", {"path": "kira.txt"})
            with self.agent._use_session("ren"):
                self.agent._turn_cache["ren"] = "keep"
                self.agent._memos.append((2.0, "Ren memo"))
                self.agent._last_cats = {"web"}
                self.agent._last_used_turn = 2
                self.agent.last_results = ["Ren result"]
                self.access.begin_turn("research Ren")
                self.access.grant("write_file", {"path": "ren.txt"})

            self.agent.clear_session("kira")

            with self.agent._use_session("kira"):
                self.assertEqual(self.agent._turn_cache, {})
                self.assertEqual(list(self.agent._memos), [])
                self.assertEqual(self.agent._last_cats, set())
                self.assertEqual(self.agent._last_used_turn, -99)
                self.assertEqual(self.agent.last_results, [])
                self.assertEqual(self.access.user_text, "")
                self.assertFalse(self.access.tainted)
                self.assertFalse(self.access.consume_grant("write_file", {"path": "kira.txt"}))
            with self.agent._use_session("ren"):
                self.assertEqual(self.agent._turn_cache["ren"], "keep")
                self.assertEqual(list(self.agent._memos), [(2.0, "Ren memo")])
                self.assertEqual(self.agent._last_cats, {"web"})
                self.assertEqual(self.agent._last_used_turn, 2)
                self.assertEqual(self.agent.last_results, ["Ren result"])
                self.assertTrue(self.access.consume_grant("write_file", {"path": "ren.txt"}))

            self.assertEqual(cleared_owners, ["kira"])
            self.assertIsNone(self.agent.tasks.active("kira"))
            self.assertIs(self.agent.tasks.active("ren"), ren_task)

    def test_release_session_drops_ephemeral_state_but_keeps_durable_task(self):
        with TemporaryDirectory() as temp:
            self.agent._init_autonomy(Path(temp))
            durable = self.agent.tasks.new("resume this later", session_id="kira")
            with self.agent._use_session("kira"):
                self.agent._turn_cache["read_file{}"] = "temporary result"
                self.agent._memos.append((1.0, "temporary memo"))
                self.agent.last_results = ["temporary result"]
                self.access.grant("write_file", {"path": "safe.txt"})
            self.agent._pending_by_session["kira"] = Pending(
                "delete_file", {"path": "safe.txt"}, "delete",
                session_id="kira",
            )
            self.agent._pending_new_sessions.add("kira")
            CANCEL.cancel_session("kira")

            self.assertTrue(self.agent.release_session("kira"))

            self.assertNotIn("kira", self.agent._session_states)
            self.assertFalse(self.access.release_session("kira"))
            self.assertNotIn("kira", self.agent._pending_by_session)
            self.assertNotIn("kira", self.agent._pending_new_sessions)
            self.assertIs(self.agent.tasks.active("kira"), durable)
            self.assertTrue(CANCEL.release_session("kira") is False)


    def test_mood_context_keeps_background_character_state_separate(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            kira_runtime = EmotionalRuntime(path=root / "kira_emotional_state.json")
            with patch.object(mood, "DATA_DIR", root), \
                 patch.object(mood, "_RUNTIME_CACHE", {"kira": kira_runtime}), \
                 patch.object(mood, "_RUNTIME_MIGRATED_IDS", set()), \
                 patch.object(mood, "_ACTIVE_CHARACTER_ID", "kira"), \
                 patch.object(mood, "_emotional_runtime", kira_runtime):
                mood.set_active_character("kira")
                with mood.character_scope("ren"):
                    self.assertEqual(mood._current_character_id(), "ren")
                    self.assertEqual(
                        mood._path(),
                        root / "characters" / "ren" / "legacy_mood.json",
                    )
                    mood.on_user_message("امروز خیلی ناراحتم و حالم خوب نیست", now=1000)
                    self.assertIn("down", mood.current(now=1000)["user_states"])
                    ren_runtime = mood._runtime_for()
                    self.assertIsNot(ren_runtime, kira_runtime)

                self.assertEqual(mood._current_character_id(), "kira")
                self.assertNotIn("down", mood.current(now=1000)["user_states"])
                self.assertTrue((root / "characters" / "ren" / "legacy_mood.json").exists())
                self.assertTrue((root / "characters" / "ren" / "emotional_state.json").exists())

    def test_mood_character_scope_restores_nested_context(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            kira_runtime = EmotionalRuntime(path=root / "kira_emotional_state.json")
            with patch.object(mood, "DATA_DIR", root), \
                 patch.object(mood, "_RUNTIME_CACHE", {"kira": kira_runtime}), \
                 patch.object(mood, "_RUNTIME_MIGRATED_IDS", set()), \
                 patch.object(mood, "_ACTIVE_CHARACTER_ID", "kira"), \
                 patch.object(mood, "_emotional_runtime", kira_runtime):
                mood.set_active_character("kira")
                with mood.character_scope("ren"):
                    self.assertEqual(mood._current_character_id(), "ren")
                    with mood.character_scope("mika"):
                        self.assertEqual(mood._current_character_id(), "mika")
                    self.assertEqual(mood._current_character_id(), "ren")
                self.assertEqual(mood._current_character_id(), "kira")

    def test_task_cancel_releases_only_the_matching_session_confirmation(self):
        with TemporaryDirectory() as temp:
            self.agent._init_autonomy(Path(temp))
            plan = self.agent.tasks.new("remove a file", session_id="kira")
            self.agent._pending_by_session["kira"] = Pending(
                "delete_file", {"path": "safe.txt"}, "delete file",
                plan_id=plan.id, session_id="kira",
            )
            self.agent._pending_new_sessions.add("kira")
            self.agent._pending_by_session["ren"] = Pending(
                "delete_file", {"path": "other.txt"}, "delete another file",
                plan_id="ren-plan", session_id="ren",
            )
            self.agent._pending_new_sessions.add("ren")

            reply = self.agent.handle_task_command("لغو کار", session_id="kira")

            self.assertIn("وظیفه لغو شد", reply)
            self.assertEqual(plan.status, "cancelled")
            self.assertNotIn("kira", self.agent._pending_by_session)
            self.assertNotIn("kira", self.agent._pending_new_sessions)
            self.assertIn("ren", self.agent._pending_by_session)
            self.assertIn("ren", self.agent._pending_new_sessions)

    def test_task_history_retention_is_independent_for_each_character(self):
        with TemporaryDirectory() as temp:
            store = TaskStore(Path(temp))
            owners = ("kira", "ren", "mika")
            for index in range(HISTORY_KEEP + 3):
                for owner in owners:
                    finished = store.new(
                        f"{owner} completed {index}", session_id=owner
                    )
                    finished.status = P_DONE

            active = {
                owner: store.new(f"{owner} active task", session_id=owner)
                for owner in owners
            }
            store.save()

            restored = TaskStore(Path(temp))
            for owner in owners:
                own_history = [
                    plan for plan in restored.plans if plan.session_id == owner
                ]
                self.assertEqual(len(own_history), HISTORY_KEEP + 1)
                self.assertIs(restored.active(owner), next(
                    plan for plan in own_history if plan.goal == f"{owner} active task"
                ))
                self.assertNotIn(
                    f"{owner} completed 0",
                    [plan.goal for plan in own_history],
                )
            self.assertEqual(
                {owner: restored.active(owner).goal for owner in owners},
                {owner: f"{owner} active task" for owner in owners},
            )

    def test_task_store_active_history_and_clear_are_character_scoped(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            store = TaskStore(root)
            kira = store.new("Kira project task", session_id="kira")
            ren = store.new("Ren research task", session_id="ren")
            mika = store.new("Mika note", session_id="mika")

            self.assertIs(store.active("kira"), kira)
            self.assertIs(store.active("ren"), ren)
            self.assertIs(store.active("mika"), mika)

            store.save()
            restored = TaskStore(root)
            self.assertEqual(restored.active("kira").goal, "Kira project task")
            self.assertEqual(restored.active("ren").goal, "Ren research task")
            self.assertEqual(restored.active("mika").goal, "Mika note")

            restored.clear("ren")
            self.assertIsNone(restored.active("ren"))
            self.assertEqual(restored.active("kira").goal, "Kira project task")
            self.assertEqual(restored.active("mika").goal, "Mika note")

    def test_webintel_research_storage_is_independent_and_persistent_per_character(self):
        owner = ContextVar("test_webintel_owner", default="")
        with TemporaryDirectory() as temp:
            store = SessionScopedResearchStore(temp, owner.get)

            owner.set("kira")
            kira_session = store.start("Kira research", dict(DEFAULT_BUDGET))
            kira_session.status = "paused"
            store.save()

            owner.set("ren")
            self.assertIsNone(store.current())
            store.start("Ren research", dict(DEFAULT_BUDGET))
            store.save()

            owner.set("kira")
            self.assertEqual(store.current().topic, "Kira research")
            restarted = SessionScopedResearchStore(temp, owner.get)
            self.assertEqual(restarted.current().topic, "Kira research")

            owner.set("ren")
            self.assertEqual(restarted.current().topic, "Ren research")
            restarted.clear()
            self.assertIsNone(restarted.current())

            owner.set("kira")
            self.assertEqual(restarted.current().topic, "Kira research")
            self.assertTrue(restarted.release_session("kira"))
            self.assertEqual(restarted.current().topic, "Kira research")

    def test_webintel_cancel_event_is_scoped_to_active_owner(self):
        CANCEL.clear_all()
        try:
            CANCEL.activate("brand-new-owner")
            self.assertFalse(CANCEL.is_set())
            CANCEL.set()
            self.assertTrue(CANCEL.is_set())
            CANCEL.deactivate("brand-new-owner")

            CANCEL.cancel_session("kira")
            CANCEL.activate("ren")
            self.assertFalse(CANCEL.is_set())
            CANCEL.set()
            self.assertTrue(CANCEL.is_set())
            CANCEL.deactivate("ren")

            CANCEL.activate("kira")
            self.assertTrue(CANCEL.is_set())
            CANCEL.clear()
            self.assertFalse(CANCEL.is_set())
            CANCEL.deactivate("kira")
        finally:
            CANCEL.deactivate("ren")
            CANCEL.deactivate("kira")
            CANCEL.clear_all()

    def test_brain_hints_and_turns_are_isolated_per_character(self):
        with TemporaryDirectory() as temp:
            with patch.object(brain, "DATA_DIR", Path(temp)):
                brain.reset_state("kira")
                brain.reset_state("ren")

                self.assertEqual(brain._path("kira"), Path(temp) / brain.STATE_NAME)
                self.assertNotEqual(brain._path("ren"), brain._path("kira"))

                self.assertTrue(brain._store_hint("same-signature", "Kira-only hint", "kira"))
                self.assertTrue(brain._store_hint("same-signature", "Ren-only hint", "ren"))
                kira_state = brain._load("kira")
                kira_state["writer"] = {"last_run": 123, "next_try": 456}
                brain._save(kira_state, "kira")
                self.assertEqual(brain._load("kira")["hint"]["text"], "Kira-only hint")
                self.assertEqual(brain._load("ren")["hint"]["text"], "Ren-only hint")

                brain.reset_state("kira")
                reset_kira = brain._load("kira")
                self.assertIsNone(reset_kira["hint"])
                self.assertEqual(reset_kira["writer"], {"last_run": 123, "next_try": 456})
                self.assertEqual(brain._load("ren")["hint"]["text"], "Ren-only hint")

                with patch("kira.hybrid_ai.HybridRouter._write_telemetry"):
                    brain.after_turn(
                        None, {}, brain.Decision(reflection="off"),
                        "hello", "answer", character_id="ren",
                    )
                self.assertEqual(brain._load("ren")["turn"], 1)
                self.assertEqual(brain._load("kira")["turn"], 0)

    def test_brain_prompt_consumes_only_the_current_character_hint(self):
        with TemporaryDirectory() as temp:
            with patch.object(brain, "DATA_DIR", Path(temp)):
                brain._store_hint("kira", "Only Kira context", "kira")
                brain._store_hint("ren", "Only Ren context", "ren")
                decision = brain.Decision()
                kira_prompt = brain.extend_prompt("base", decision, character_id="kira")
                ren_prompt = brain.extend_prompt("base", decision, character_id="ren")
                mika_prompt = brain.extend_prompt("base", decision, character_id="mika")

                self.assertIn("Only Kira context", kira_prompt)
                self.assertNotIn("Only Ren context", kira_prompt)
                self.assertIn("Only Ren context", ren_prompt)
                self.assertNotIn("Only Kira context", ren_prompt)
                self.assertNotIn("Only Kira context", mika_prompt)
                self.assertNotIn("Only Ren context", mika_prompt)

    def test_plan_carries_its_character_identity(self):
        plan = ToolPlan({"files"}, session_id="mika")
        self.assertEqual(plan.session_id, "mika")


if __name__ == "__main__":
    unittest.main()
