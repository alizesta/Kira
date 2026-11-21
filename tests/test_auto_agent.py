"""Kode autonomous engine (Qt-free): tools, safety gates, test/fix loop, zip delivery."""
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from kira import auto_agent as aa


class Script:
    """A router that replays prepared model replies (dicts become JSON) and records what it was shown.

    Planner and reviewer calls are answered from their own slots so ``replies`` only describes the
    agent's decision loop: those two are infrastructure calls, not scripted agent steps.
    """
    def __init__(self, *replies, plan="1. inspect\\n2. make the smallest correct change\\n3. run focused tests", review="CLEAN"):
        self.replies, self.seen, self.observations = list(replies), [], []
        self.plan, self.review = plan, review
        self.review_calls = 0
        # Keep legacy scenario scripts realistic under the stricter source-read/plan gates.
        first_mutation = next((i for i, r in enumerate(self.replies)
                               if isinstance(r, dict) and r.get("action") in ("write", "replace", "delete", "memory")), None)
        if first_mutation is not None:
            prior = self.replies[:first_mutation]
            has_plan = any(isinstance(r, dict) and r.get("action") == "plan" for r in prior)
            has_read = any(isinstance(r, dict) and r.get("action") == "read" for r in prior)
            if has_plan and not has_read:
                plan_index = next(i for i, r in enumerate(prior)
                                   if isinstance(r, dict) and r.get("action") == "plan")
                self.replies.insert(plan_index, {"action": "read", "path": "calc.py"})
            elif not has_plan:
                action = self.replies[first_mutation]
                path = str(action.get("path") or "")
                read_path = path if path in ("calc.py", "test_calc.py", "pkg/m.py") else "calc.py"
                if path == "pkg":
                    read_path = "pkg/m.py"
                self.replies[first_mutation:first_mutation] = [
                    {"action": "read", "path": read_path},
                    {"action": "plan", "steps": ["inspect source", "make requested change", "verify"]},
                ]

    def chat_stream(self, messages, system, temperature=0.2, on_chunk=None, **kw):
        if messages and messages[-1].get("role") == "user" and str(messages[-1].get("content", "")).startswith("RESULT (untrusted data):"):
            self.observations.append(messages[-1]["content"])
        if system == aa.PLAN_PROMPT or "senior software architect" in str(system).lower():
            return {"text": self.plan}
        if "independent code reviewer" in str(system).lower():
            self.review_calls += 1
            return {"text": self.review}
        self.seen.append([m["content"] for m in messages])
        r = self.replies.pop(0)
        return {"text": r if isinstance(r, str) else json.dumps(r)}


FIXED_NOW = datetime(2026, 11, 12, 10, 54, tzinfo=timezone.utc)      # = 14:24 in Iran


class AgentBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.proj, self.out = base / "Demo", base / "out"
        self.proj.mkdir()
        (self.proj / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (self.proj / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
            "if __name__ == '__main__':\n    unittest.main()\n", encoding="utf-8")
        (self.proj / ".env").write_text("TOKEN=super-secret", encoding="utf-8")
        (self.proj / "node_modules").mkdir()
        (self.proj / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
        self.events = []

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, router, **kw):
        kw.setdefault("python", sys.executable)
        self.assertIs(aa.AutoAgent, aa.KodeAutonomousEngine)
        return aa.KodeAutonomousEngine(router, self.proj, kw.pop("goal", "fix add"), on_event=self.events.append, output_dir=self.out,
                            now=FIXED_NOW, **kw)

    def zip_text(self, result, name):
        with zipfile.ZipFile(result["zip"]) as zf:
            return zf.read(name).decode("utf-8")


class UiGuidanceTests(AgentBase):
    def test_auto_agent_selects_ui_guidance_from_goal_without_changing_backend_tasks(self):
        ui_agent = self.agent(Script(), goal="بازطراحی صفحه تنظیمات")
        self.assertIn("APPLLAMMA APP-DESIGN WORKFLOW", ui_agent.system_prompt)
        self.assertIn("Connectedness", ui_agent.system_prompt)

        backend_agent = self.agent(Script(), goal="Fix the database migration")
        self.assertNotIn("APPLLAMMA APP-DESIGN WORKFLOW", backend_agent.system_prompt)

        class CapturingRouter:
            def __init__(self):
                self.system = ""

            def chat_stream(self, messages, system, **kwargs):
                self.system = system
                return {"text": "ok"}

        router = CapturingRouter()
        ui_agent.router = router
        ui_agent._ask_model([{"role": "user", "content": "inspect UI"}])
        self.assertIn("APPLLAMMA APP-DESIGN WORKFLOW", router.system)




class FullLoopTests(AgentBase):
    def test_inspect_plan_edit_test_fix_retest_package(self):
        router = Script(
            {"action": "list"},
            {"action": "read", "path": "calc.py"},
            {"action": "plan", "steps": ["fix add", "run tests"]},
            {"action": "search", "pattern": "def add"},
            {"action": "run", "args": ["python", "-m", "unittest", "-v"]},          # fails: the bug is still there
            {"action": "replace", "path": "calc.py", "old": "return a - b", "new": "return a + b"},
            {"action": "run", "args": ["python", "-m", "unittest", "-v"]},          # passes
            {"action": "review"},
            {"action": "finish", "summary": "add() subtracted; fixed, tests pass"},
        )
        result = self.agent(router).run()
        self.assertEqual([c for _, c in result["runs"]], [1, 0])
        self.assertEqual(result["changed"], ["calc.py"])
        self.assertEqual(result["summary"], "add() subtracted; fixed, tests pass")
        # delivered zip: fixed file, report, timestamped Iran-time name, healthy
        self.assertEqual(result["zip"].name, "Demo_2026-11-12_14-24_IRST.zip")
        self.assertIn("a + b", self.zip_text(result, "calc.py"))
        self.assertIn("calc.py", self.zip_text(result, "KODE_REPORT.md"))
        self.assertEqual(result["zip_info"]["files"], len(zipfile.ZipFile(result["zip"]).namelist()))
        # the original project is untouched; secrets and runtime folders never reach the copy or the zip
        self.assertIn("a - b", (self.proj / "calc.py").read_text(encoding="utf-8"))
        names = zipfile.ZipFile(result["zip"]).namelist()
        self.assertNotIn(".env", names)
        self.assertFalse(any("node_modules" in n for n in names))
        self.assertTrue(any("🗺" in e for e in self.events))                        # the plan was shown
        self.assertTrue(any("```" in e and "exit 1" in e for e in self.events))     # the failing test log reached the chat

    def test_observations_are_fed_back_to_the_model(self):
        router = Script({"action": "read", "path": "calc.py"}, {"action": "finish", "summary": "ok"})
        self.agent(router).run()
        self.assertIn("1: def add(a, b):", router.seen[1][-1])


class SafetyTests(AgentBase):
    def run_one(self, action, verify=True, **kw):
        # a changed working copy must pass a check and a clean review before finish is accepted
        if verify:
            router = Script(action,
                            {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                            {"action": "review"},
                            {"action": "finish", "summary": "x"})
        else:
            router = Script(action, {"action": "finish", "summary": "x"})
        result = self.agent(router, **kw).run()
        plan_index = next((i for i, item in enumerate(router.observations)
                           if "independently reviewed plan recorded" in item), -1)
        obs = router.observations[plan_index + 1] if plan_index >= 0 and plan_index + 1 < len(router.observations) else (router.observations[-1] if router.observations else "")
        return obs, result

    def test_paths_cannot_escape_or_touch_secrets(self):
        for bad in ("../evil.py", "/etc/passwd", "C:/Windows/x.py", ".env", "node_modules/a.js"):
            obs, _ = self.run_one({"action": "write", "path": bad, "content": "x"}, verify=False)
            self.assertIn("ERROR", obs, bad)
        self.assertFalse((self.proj.parent / "evil.py").exists())

    def test_only_python_checks_run_without_approval(self):
        for args in (["python", "-c", "print(1)"], ["powershell", "-Command", "ls"], ["python", "-m", "pip", "install", "x"],
                     ["python", "-m", "unittest", "../x"], ["python", "-m", "unittest", "a;b"]):
            obs, result = self.run_one({"action": "run", "args": args}, verify=False)
            self.assertIn("ERROR", obs, args)
            self.assertEqual(result["runs"], [])

    def test_shell_needs_approval_every_time(self):
        asked = []
        shell = (sys.executable, ["-c"])
        obs, result = self.run_one({"action": "shell", "command": "print('hi-from-shell')"}, shell=shell,
                                   approve=lambda c: asked.append(c) or False, verify=False)
        self.assertIn("تأیید نکرد", obs)
        self.assertEqual(result["runs"], [])
        obs, result = self.run_one({"action": "shell", "command": "print('hi-from-shell')"}, shell=shell,
                                   approve=lambda c: asked.append(c) or True, verify=False)
        self.assertIn("hi-from-shell", obs)
        self.assertEqual(len(asked), 2)
        router = Script({"action": "shell", "command": "ls"}, {"action": "finish", "summary": "x"})
        agent = self.agent(router, approve=lambda c: True)
        agent.shell = None                                                                # simulate an OS without a shell
        agent.run()
        self.assertIn("ERROR", router.seen[1][-1])

    def test_deleting_a_file_is_free_but_a_folder_needs_approval(self):
        (self.proj / "pkg").mkdir()
        (self.proj / "pkg" / "m.py").write_text("x", encoding="utf-8")
        obs, result = self.run_one({"action": "delete", "path": "calc.py"})
        self.assertEqual(result["removed"], ["calc.py"])
        obs, result = self.run_one({"action": "delete", "path": "pkg"}, approve=lambda c: False, verify=False)
        self.assertIn("تأیید نکرد", obs)
        self.assertEqual(result["removed"], [])
        obs, result = self.run_one({"action": "delete", "path": "pkg"}, approve=lambda c: True)
        self.assertEqual(result["removed"], ["pkg/m.py"])
        self.assertTrue((self.proj / "pkg" / "m.py").exists())                         # the original still has it

    def test_secrets_are_masked_in_what_the_model_reads(self):
        (self.proj / "cfg.py").write_text('password = "hunter2"\n', encoding="utf-8")
        obs, _ = self.run_one({"action": "read", "path": "cfg.py"}, verify=False)
        self.assertNotIn("hunter2", obs)

    def test_unknown_action_and_bad_json_are_survivable_but_bounded(self):
        obs, _ = self.run_one({"action": "format_disk"}, verify=False)
        self.assertIn("not available", obs)
        result = self.agent(Script("no json", "still no", "nope")).run()
        self.assertIn("JSON", result["summary"])
        self.assertIsNone(result["zip"])
        self.assertTrue(result["resume_available"])

    def test_step_budget_and_stop(self):
        result = self.agent(Script(*[{"action": "list"}] * 5), max_steps=3).run()
        self.assertEqual(result["steps"], 3)
        self.assertIn("تکراری", result["summary"])
        flag = {"stop": False}

        class Stopper(Script):
            def chat_stream(s, messages, system, *a, **k):
                reply = super().chat_stream(messages, system, *a, **k)
                if system != aa.PLAN_PROMPT:
                    flag["stop"] = True
                return reply
        result = self.agent(Stopper({"action": "list"}, {"action": "list"}), should_stop=lambda: flag["stop"]).run()
        self.assertTrue(result["stopped"])
        self.assertIsNone(result["zip"])
        self.assertTrue(result["resume_available"])

    def test_external_edit_of_the_original_is_reported(self):
        class Meddler(Script):
            def chat_stream(s, *a, **k):
                (self.proj / "calc.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
                return super().chat_stream(*a, **k)
        result = self.agent(Meddler({"action": "finish", "summary": "x"})).run()
        self.assertEqual(result["external"], ["calc.py"])
        self.assertIn("هشدار", self.zip_text(result, "KODE_REPORT.md"))

    def test_long_running_command_is_killed_by_stop(self):
        flag = {"stop": False}
        import threading
        threading.Timer(1.0, lambda: flag.update(stop=True)).start()
        (self.proj / "slow.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        agent = self.agent(Script({"action": "shell", "command": "import time; time.sleep(60)"}, {"action": "finish", "summary": "x"}),
                           shell=(sys.executable, ["-c"]), approve=lambda c: True, should_stop=lambda: flag["stop"])
        import time
        t0 = time.time()
        result = agent.run()
        self.assertLess(time.time() - t0, 20)
        self.assertTrue(result["stopped"])


class QualityTests(AgentBase):
    def test_syntax_error_is_reported_to_the_model_immediately(self):
        router = Script({"action": "write", "path": "calc.py", "content": "def add(a, b)\n    return a + b\n"},
                        {"action": "write", "path": "data.json", "content": "{bad"},
                        {"action": "write", "path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
                        {"action": "write", "path": "data.json", "content": "{}"},
                        {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                        {"action": "review"},
                        {"action": "finish", "summary": "x"})
        self.agent(router).run()
        self.assertTrue(any("SYNTAX ERROR in calc.py line 1" in item for item in router.observations))
        self.assertTrue(any("INVALID JSON" in item for item in router.observations))
        self.assertTrue(any("SYNTAX ERROR" in e for e in self.events))

    def test_finish_is_held_back_once_until_a_check_passed_after_the_last_edit(self):
        router = Script({"action": "replace", "path": "calc.py", "old": "a - b", "new": "a + b"},
                        {"action": "finish", "summary": "done"},                               # too early
                        {"action": "run", "args": ["python", "-m", "unittest"]},
                        {"action": "review"},
                        {"action": "finish", "summary": "done, tests pass"})
        result = self.agent(router).run()
        self.assertTrue(any("GATE" in message for call in router.seen for message in call))
        self.assertEqual(result["summary"], "done, tests pass")
        self.assertEqual(result["runs"][0][1], 0)

    def test_gate_requires_a_check_and_a_clean_review_after_a_change(self):
        router = Script({"action": "write", "path": "new.txt", "content": "x"},
                        {"action": "finish", "summary": "a"},                                  # too early
                        {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                        {"action": "review"},
                        {"action": "finish", "summary": "final"})
        result = self.agent(router).run()
        self.assertTrue(any("GATE" in message for call in router.seen for message in call))  # the check gate spoke
        self.assertEqual(result["summary"], "final")
        router = Script({"action": "read", "path": "calc.py"}, {"action": "finish", "summary": "just looked"})
        self.assertEqual(self.agent(router).run()["summary"], "just looked")                   # nothing changed: no gate

    def test_first_message_has_brief_history_and_goal_in_the_users_words(self):
        router = Script({"action": "finish", "summary": "x"})
        history = [{"role": "user", "content": "فایل calc یه باگ داره"}, {"role": "assistant", "content": "باشه"}]
        self.agent(router, goal="همون باگ رو درست کن", history=history).run()
        first = router.seen[0][0]
        self.assertIn("همون باگ رو درست کن", first)
        self.assertIn("RECENT CONVERSATION", first)
        self.assertIn("فایل calc یه باگ داره", first)
        self.assertIn("PROJECT BRIEF", first)
        self.assertIn("unittest", first)                                                      # how to run this project's tests

    def test_project_brief_describes_stack_and_tests(self):
        brief = aa.project_brief(self.proj)
        self.assertIn(".py x2", brief)
        self.assertIn("Tests: present", brief)
        self.assertNotIn("super-secret", brief)

    def test_prompt_demands_complete_removals_and_real_verification(self):
        self.assertIn("ALL of it", aa.SYSTEM_PROMPT)
        self.assertIn("root cause", aa.SYSTEM_PROMPT)
        self.assertIn("never weaken", aa.SYSTEM_PROMPT.lower().replace("never weaken, skip or delete", "never weaken"))


class ReadonlyTests(AgentBase):
    def test_readonly_answers_without_copying_writing_or_zipping(self):
        router = Script({"action": "search", "pattern": "def add"},
                        {"action": "write", "path": "calc.py", "content": "x"},
                        {"action": "run", "args": ["python", "-m", "unittest"]},
                        {"action": "finish", "summary": "add() در calc.py خط ۱ است"})
        result = self.agent(router, readonly=True).run()
        self.assertTrue(result["readonly"])
        self.assertIsNone(result["zip"])
        self.assertIn("calc.py", result["summary"])
        self.assertTrue(any("not available in read-only mode" in item for item in router.observations))
        self.assertIn("a - b", (self.proj / "calc.py").read_text(encoding="utf-8"))
        self.assertFalse(self.out.exists())


class ExecutionGuardTests(AgentBase):
    """Task 004: no AutoAgent path (run / shell / file tools, pre-plan AST map) bypasses the app-level
    ToolRegistry.execution_guard (tools_mode=off, Competitive Safe). The guard must fail closed."""

    def test_guard_blocks_every_execution_and_file_tool(self):
        approved, denied = [], []
        router = Script(
            {"action": "write", "path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
            {"action": "run", "args": ["python", "-m", "unittest", "-v"]},
            {"action": "shell", "command": "echo pwned > pwned.txt"},
            {"action": "delete", "path": "calc.py"},
            {"action": "finish", "summary": "blocked"},
        )
        result = self.agent(router, approve=lambda c: approved.append(c) or True,
                            execution_guard=lambda tool: denied.append(tool.name) or "ابزارها خاموش است.").run()
        self.assertIn("شش اقدام پیاپی", result["summary"])
        self.assertIsNone(result["zip"])
        self.assertEqual(result["changed"], [])                # nothing was written to the working copy
        self.assertEqual(result["runs"], [])                   # no process ran: neither python nor PowerShell
        self.assertEqual(approved, [])                         # shell / folder-delete approvals were never even asked
        self.assertEqual(denied, ["map", "read", "plan", "write", "run", "shell", "delete"])
        self.assertTrue(any("⛔" in e for e in self.events))
        self.assertIn("ERROR: ابزارها خاموش است.", router.seen[1][-1])

    def test_guard_receives_a_name_and_categories(self):
        seen = []

        def guard(tool):
            seen.append((tool.name, tuple(tool.categories)))
            return "blocked"

        router = Script({"action": "run", "args": ["python", "-m", "unittest", "-v"]}, {"action": "finish", "summary": "x"})
        self.agent(router, execution_guard=guard).run()
        self.assertIn(("run", ("system",)), seen)

    def test_guard_failure_fails_closed(self):
        def broken(tool):
            raise RuntimeError("guard down")

        router = Script({"action": "write", "path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
                        {"action": "finish", "summary": "x"})
        result = self.agent(router, execution_guard=broken).run()
        self.assertEqual(result["changed"], [])                # a broken guard must never open the door
        self.assertTrue(any("مسدود" in e for e in self.events))

    def test_guard_may_allow_reads_but_still_blocks_execution(self):
        def guard(tool):
            return None if tool.name in ("list", "map", "read", "search") else "فقط خواندن مجاز است."

        router = Script({"action": "read", "path": "calc.py"},
                        {"action": "run", "args": ["python", "-m", "unittest", "-v"]},
                        {"action": "finish", "summary": "done"})
        result = self.agent(router, execution_guard=guard).run()
        self.assertEqual(result["summary"], "done")
        self.assertEqual(result["runs"], [])
        self.assertIn("1: def add", router.seen[1][-1])        # the allowed read really happened
        self.assertIn("ERROR: فقط خواندن مجاز است.", router.seen[2][-1])

    def test_guard_blocks_the_pre_plan_ast_map_too(self):
        denied = []

        def guard(tool):
            r = "مسدود" if tool.name != "plan" else None
            if r:
                denied.append(tool.name)
            return r

        router = Script({"action": "finish", "summary": "x"})
        self.agent(router, execution_guard=guard).run()
        self.assertIn("map", denied)                           # the direct pre-step AST map is guarded as well
        self.assertNotIn("PYTHON AST MAP", router.seen[0][0])


class TaskFiveStabilityTests(AgentBase):
    """Task 005: bounded review gate, non-Python checks, safe delivery and durable memory."""

    def test_finish_gate_is_bounded_when_the_model_never_verifies(self):
        router = Script({"action": "write", "path": "note.txt", "content": "x"},
                        *[{"action": "finish", "summary": "done"}] * 10)
        result = self.agent(router, max_steps=20).run()
        self.assertLessEqual(result["steps"], aa.MAX_GATE_STEPS)
        self.assertIn("تکراری", result["summary"])
        self.assertIsNone(result["zip"])                       # unfinished work is never packaged as final
        self.assertTrue(result["resume_available"])
        self.assertEqual(result["changed"], ["note.txt"])

    def test_non_python_project_checks_are_allowed(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}))
        for args in (["npm", "test"], ["npm", "run", "build"], ["yarn", "test"], ["cargo", "test"],
                     ["go", "test", "./..."], ["dotnet", "build"], ["gradle", "test"], ["node", "--check", "app.js"]):
            self.assertEqual(agent.validate_run(list(args)), args)
        for args in (["npm", "install"], ["npm", "run", "deploy"], ["cargo", "publish"],
                     ["npx", "anything"], ["bash", "test"], ["go", "run", "main.go"]):
            with self.assertRaises(ValueError, msg=args):
                agent.validate_run(list(args))

    def test_non_python_check_is_executed_as_given(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}))
        agent.work = self.proj
        calls = []
        agent._exec = lambda cmd: (calls.append(cmd), (0, "ok"))[1]
        obs = agent.tool_run({"args": ["npm", "test"]})
        self.assertIn("exit code: 0", obs)
        self.assertEqual(calls, [["npm", "test"]])

    def test_zip_delivery_never_overwrites_an_earlier_zip(self):
        first = self.agent(Script({"action": "finish", "summary": "one"})).run()
        second = self.agent(Script({"action": "finish", "summary": "two"})).run()
        self.assertNotEqual(first["zip"], second["zip"])
        self.assertTrue(first["zip"].exists())
        self.assertTrue(second["zip"].exists())
        self.assertIn("_2_", second["zip"].name)
        self.assertTrue(second["zip"].name.endswith("_IRST.zip"))

    def test_project_memory_is_durable_outside_the_working_copy(self):
        memory_dir = Path(self.tmp.name) / "durable-memory"
        router = Script({"action": "memory", "content": "Always run npm test before delivery."},
                        {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                        {"action": "review"},
                        {"action": "finish", "summary": "stored"})
        result = self.agent(router, memory_dir=memory_dir).run()
        files = list(memory_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("npm test", files[0].read_text(encoding="utf-8"))
        self.assertIn(".ai1/PROJECT_MEMORY.md", zipfile.ZipFile(result["zip"]).namelist())
        later = Script({"action": "finish", "summary": "read it"})
        self.agent(later, memory_dir=memory_dir).run()
        self.assertIn("Always run npm test before delivery.", later.seen[0][0])

    def test_working_copy_checkpoint_survives_when_the_mission_raises(self):
        class Boom(Script):
            def chat_stream(self, *a, **k):
                raise RuntimeError("model exploded")
        agent = self.agent(Boom())
        with self.assertRaises(RuntimeError):
            agent.run()
        self.assertTrue(agent.session_file.exists())
        self.assertTrue((agent.session_dir / "Demo").exists())

    def test_snapshot_skips_unreadable_files_instead_of_crashing(self):
        with mock.patch.object(aa.Path, "open", side_effect=OSError("access denied")):
            self.assertEqual(aa.snapshot(self.proj), {})

    def test_unique_zip_path_keeps_the_timestamp_pattern(self):
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        (out / aa.zip_name("Demo", FIXED_NOW)).write_bytes(b"old")
        path = aa.unique_zip_path(out, "Demo", FIXED_NOW)
        self.assertEqual(path.name, "Demo_2_2026-11-12_14-24_IRST.zip")


class HelperTests(unittest.TestCase):
    def test_zip_name_uses_gregorian_date_and_iran_time(self):
        self.assertEqual(aa.zip_name("ProjectKira", FIXED_NOW), "ProjectKira_2026-11-12_14-24_IRST.zip")
        self.assertEqual(aa.zip_name("my proj!", FIXED_NOW), "my_proj_2026-11-12_14-24_IRST.zip")
        late = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)           # 00:30 next day in Iran
        self.assertEqual(aa.iran_stamp(late), "2026-11-13_00-30")

    def test_parse_action_tolerates_chatter_and_fences(self):
        self.assertEqual(aa.parse_action('بله:\n```json\n{"action":"list"}\n```')["action"], "list")
        self.assertIsNone(aa.parse_action("no json here"))
        self.assertEqual(aa.parse_action('{"x":1} {"action":"read","path":"a"}')["action"], "read")


class ReliabilityTests(AgentBase):
    def test_replace_rejects_result_larger_than_readable_file_limit(self):
        target = self.proj / "large.txt"
        target.write_text("needle", encoding="utf-8")
        agent = self.agent(Script({"action": "finish", "summary": "unused"}))
        agent.work = self.proj
        agent._planned = True
        agent._read_paths.add("large.txt")
        agent._before_hashes = aa.snapshot(self.proj)
        with self.assertRaisesRegex(ValueError, "سقف مجاز"):
            agent.tool_replace({
                "path": "large.txt",
                "old": "needle",
                "new": "x" * (aa.MAX_FILE_BYTES + 1),
            })
        self.assertEqual(target.read_text(encoding="utf-8"), "needle")
        self.assertFalse(list(self.proj.glob(".large.txt.*.tmp")))

    def test_atomic_write_failure_preserves_existing_file_and_cleans_temp(self):
        target = self.proj / "important.txt"
        target.write_text("original content", encoding="utf-8")
        with mock.patch.object(aa.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                aa._atomic_write_text(target, "replacement content")
        self.assertEqual(target.read_text(encoding="utf-8"), "original content")
        self.assertFalse(list(self.proj.glob(".important.txt.*.tmp")))

    def test_large_project_files_are_bounded_and_skipped_by_map_and_search(self):
        large = self.proj / "large.py"
        large.write_bytes(b"x" * (aa.MAX_FILE_BYTES + 1))
        agent = self.agent(Script({"action": "finish", "summary": "unused"}))
        agent.work = self.proj
        with self.assertRaisesRegex(ValueError, "سقف مجاز"):
            aa._read_bounded_text(large)
        mapped = agent.tool_map({})
        self.assertIn("calc.py", mapped)
        self.assertNotIn("large.py", mapped)
        found = agent.tool_search({"pattern": "return a - b", "glob": "*.py"})
        self.assertIn("calc.py:2", found)
        self.assertNotIn("large.py:", found)

    def test_project_copy_enforces_total_size_limit_before_copy(self):
        source = Path(self.tmp.name) / "source"
        destination = Path(self.tmp.name) / "copy"
        source.mkdir()
        (source / "large.bin").write_bytes(b"123")
        with mock.patch.object(aa, "MAX_COPY_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "۴۰۰ مگابایت"):
                aa.copy_project(source, destination)
        self.assertFalse((destination / "large.bin").exists())

    def test_project_copy_removes_partial_file_and_reports_path_on_copy_error(self):
        source = Path(self.tmp.name) / "source"
        destination = Path(self.tmp.name) / "copy"
        source.mkdir()
        (source / "broken.txt").write_text("content", encoding="utf-8")

        def partial_copy(_source, target):
            Path(target).write_bytes(b"partial")
            raise OSError("disk full")

        with mock.patch.object(aa.shutil, "copy2", side_effect=partial_copy):
            with self.assertRaisesRegex(ValueError, "broken.txt"):
                aa.copy_project(source, destination)
        self.assertFalse((destination / "broken.txt").exists())

    def test_mutation_requires_complete_source_read_and_independent_plan(self):
        agent = self.agent(Script({"action": "write", "path": "calc.py", "content": "bad"}))
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        with self.assertRaisesRegex(ValueError, "action=plan|برنامه"):
            agent.tool_write({"path": "calc.py", "content": "bad"})
        with self.assertRaisesRegex(ValueError, "خواندن"):
            agent.tool_plan({"steps": ["edit calc.py"]})
        agent.tool_read({"path": "calc.py"})
        result = agent.tool_plan({"steps": ["edit calc.py", "verify"]})
        self.assertIn("independently reviewed plan", result)
        self.assertTrue(agent._planned)

    def test_stopped_or_invalid_mission_does_not_deliver_unfinished_zip(self):
        result = self.agent(Script("not json", "still not json", "third invalid")).run()
        self.assertIsNone(result["zip"])
        self.assertTrue(result["resume_available"])
        self.assertTrue((self.out / ".ai1code_sessions").exists())

    def test_repeated_action_cycle_stops_without_zip(self):
        result = self.agent(Script(
            {"action": "list"}, {"action": "map"},
            {"action": "list"}, {"action": "map"},
        )).run()
        self.assertIsNone(result["zip"])
        self.assertIn("تکراری", result["summary"])

    def test_interrupted_mission_resumes_from_checkpoint(self):
        first = self.agent(Script(
            {"action": "read", "path": "calc.py"},
            {"action": "plan", "steps": ["fix calc.py", "verify"]},
            {"action": "replace", "path": "calc.py", "old": "a - b", "new": "a + b"},
        ), max_steps=3)
        partial = first.run()
        self.assertIsNone(partial["zip"])
        self.assertTrue(partial["resume_available"])
        self.assertTrue((first.session_dir / "Demo" / "calc.py").is_file())

        second = self.agent(Script(
            {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
            {"action": "review"},
            {"action": "finish", "summary": "resumed and verified"},
        ))
        resumed = second.run()
        self.assertEqual(resumed["summary"], "resumed and verified")
        self.assertIsNotNone(resumed["zip"])
        self.assertIn("a + b", self.zip_text(resumed, "calc.py"))
        self.assertFalse(second.session_dir.exists())


    def test_shell_mutation_invalidates_source_plan_check_and_review(self):
        router = Script({"action": "finish", "summary": "x"})
        agent = self.agent(router, shell=(sys.executable, ["-c"]), approve=lambda command: True)
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        agent._observed_snapshot = dict(agent._before_hashes)
        agent._planned = agent._checked = agent._reviewed = True
        agent._checked_fingerprint = agent._reviewed_fingerprint = agent._state_fingerprint()
        agent._read_paths.add("calc.py")
        obs = agent.tool_shell({"command": "open('calc.py', 'w', encoding='utf-8').write('changed')"})
        self.assertIn("Workspace changed by shell", obs)
        self.assertFalse(agent._planned)
        self.assertFalse(agent._checked)
        self.assertFalse(agent._reviewed)
        self.assertNotIn("calc.py", agent._read_paths)

    def test_not_clean_is_never_accepted_as_clean_review(self):
        router = Script(review="NOT CLEAN: the diff contains a regression")
        agent = self.agent(router)
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        (self.proj / "note.txt").write_text("new content\n", encoding="utf-8")
        agent._baseline_texts["note.txt"] = ""
        agent._observed_snapshot = aa.snapshot(self.proj)
        agent._dirty = agent._planned = True
        agent._checked = True
        agent._checked_fingerprint = agent._state_fingerprint()
        result = agent.tool_review({})
        self.assertIn("NOT CLEAN", result)
        self.assertFalse(agent._reviewed)

    def test_review_covers_all_changed_files_not_only_first_fifty(self):
        router = Script(review="CLEAN")
        agent = self.agent(router)
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        for index in range(55):
            rel = f"changed_{index:02d}.txt"
            (self.proj / rel).write_text(f"changed {index}\n", encoding="utf-8")
            agent._baseline_texts[rel] = ""
        agent._observed_snapshot = aa.snapshot(self.proj)
        agent._dirty = agent._planned = True
        agent._checked = True
        agent._checked_fingerprint = agent._state_fingerprint()
        result = agent.tool_review({})
        self.assertTrue(agent._reviewed, result)
        self.assertEqual(router.review_calls, 55)

    def test_finish_detects_out_of_band_change_after_review(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}))
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        agent._observed_snapshot = dict(agent._before_hashes)
        agent._planned = agent._checked = agent._reviewed = True
        agent._checked_fingerprint = agent._reviewed_fingerprint = agent._state_fingerprint()
        (self.proj / "surprise.txt").write_text("external change", encoding="utf-8")
        agent._refresh_gates()
        self.assertTrue(agent._dirty)
        self.assertFalse(agent._planned)
        self.assertFalse(agent._checked)
        self.assertFalse(agent._reviewed)



    def test_run_that_mutates_workspace_invalidates_all_quality_gates(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}))
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        agent._observed_snapshot = dict(agent._before_hashes)
        agent._planned = True
        agent._exec = lambda cmd: ((self.proj / "generated.txt").write_text("created by test", encoding="utf-8") or 0, "ok")
        # Use a deterministic fake check runner that mutates the working copy.
        def mutating_exec(cmd):
            (self.proj / "generated.txt").write_text("created by test", encoding="utf-8")
            return 0, "ok"
        agent._exec = mutating_exec
        obs = agent.tool_run({"args": ["python", "-m", "compileall", "-q", "."]})
        self.assertIn("Workspace changed during check", obs)
        self.assertFalse(agent._planned)
        self.assertFalse(agent._checked)
        self.assertFalse(agent._reviewed)
        self.assertEqual(agent._changed_paths(), ["generated.txt"])

    def test_review_chunks_never_exceed_budget_even_for_single_long_line(self):
        agent = self.agent(Script(review="CLEAN"))
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        long_content = "x" * (aa.MAX_REVIEW_CHUNK_CHARS * 3 + 17)
        (self.proj / "minified.js").write_text(long_content, encoding="utf-8")
        agent._baseline_texts["minified.js"] = ""
        agent._observed_snapshot = aa.snapshot(self.proj)
        agent._dirty = agent._planned = True
        agent._checked = True
        agent._checked_fingerprint = agent._state_fingerprint()
        chunks = agent._review_chunks()
        self.assertGreaterEqual(len(chunks), 4)
        self.assertTrue(all(len(chunk) <= aa.MAX_REVIEW_CHUNK_CHARS for _, chunk in chunks))



    def test_sensitive_files_created_by_shell_are_never_reviewed_or_packaged(self):
        agent = self.agent(Script(review="CLEAN"))
        agent.work = self.proj
        agent._before_hashes = aa.snapshot(self.proj)
        (self.proj / ".env").write_text("API_KEY=do-not-leak", encoding="utf-8")
        agent._baseline_texts[".env"] = ""
        agent._observed_snapshot = aa.snapshot(self.proj)
        agent._dirty = agent._planned = agent._checked = True
        agent._checked_fingerprint = agent._state_fingerprint()
        with self.assertRaisesRegex(RuntimeError, "فایل حساس تغییر کرده"):
            agent.tool_review({})
        path, _ = agent._zip("report")
        with zipfile.ZipFile(path) as zf:
            self.assertNotIn(".env", zf.namelist())
            self.assertNotIn("do-not-leak", zf.read("KODE_REPORT.md").decode("utf-8"))



    def test_delivery_report_redacts_secrets_from_goal_summary_and_commands(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}),
                           goal="fix bug; API_KEY=super-secret-value")
        agent.runs.append(("deploy --token=another-secret", 0))
        report = agent._report("completed; password=hunter2", [], [], {"skipped": 0}, False)
        self.assertNotIn("super-secret-value", report)
        self.assertNotIn("another-secret", report)
        self.assertNotIn("hunter2", report)
        self.assertIn("[REDACTED]", report)



    def test_truncated_read_does_not_satisfy_full_source_read_gate(self):
        agent = self.agent(Script({"action": "finish", "summary": "x"}))
        agent.work = self.proj
        (self.proj / "large.txt").write_text("x" * (aa.MAX_OBSERVATION * 2), encoding="utf-8")
        agent._before_hashes = aa.snapshot(self.proj)
        result = agent.tool_read({"path": "large.txt"})
        self.assertIn("READ TRUNCATED", result)
        self.assertNotIn("large.txt", agent._read_paths)



class BoundedExecutionOutputTests(unittest.TestCase):
    def test_verbose_process_output_is_bounded_and_retains_the_final_complete_line(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = object.__new__(aa.AutoAgent)
            agent.work = Path(directory)
            agent.should_stop = lambda: False
            code, output = agent._exec([
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 400000 + '\\nTAIL_MARKER\\n')",
            ])
        self.assertEqual(code, 0)
        self.assertLessEqual(len(output), aa.MAX_OBSERVATION)
        self.assertIn("TAIL_MARKER", output)
        self.assertIn("برای محدودیت حافظه حذف شد", output)


if __name__ == "__main__":
    unittest.main()
