"""Ai1 Code autonomous agent (Qt-free): tools, safety gates, test/fix loop, zip delivery."""
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
    def __init__(self, *replies, plan="1. inspect\n2. make the smallest correct change\n3. run focused tests", review="CLEAN"):
        self.replies, self.seen = list(replies), []
        self.plan, self.review = plan, review

    def chat_stream(self, messages, system, temperature=0.2, on_chunk=None, **kw):
        if system == aa.PLAN_PROMPT:
            return {"text": self.plan}
        if "independent code reviewer" in str(system).lower():
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
        return aa.AutoAgent(router, self.proj, kw.pop("goal", "fix add"), on_event=self.events.append, output_dir=self.out,
                            now=FIXED_NOW, **kw)

    def zip_text(self, result, name):
        with zipfile.ZipFile(result["zip"]) as zf:
            return zf.read(name).decode("utf-8")


class FullLoopTests(AgentBase):
    def test_inspect_plan_edit_test_fix_retest_package(self):
        router = Script(
            {"action": "list"},
            {"action": "plan", "steps": ["read calc.py", "fix add", "run tests"]},
            {"action": "search", "pattern": "def add"},
            {"action": "read", "path": "calc.py"},
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
        self.assertIn("calc.py", self.zip_text(result, "AI1CODE_REPORT.md"))
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
        return router.seen[1][-1], result

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
        self.assertTrue(result["zip"].exists())                                          # a zip is delivered even then

    def test_step_budget_and_stop(self):
        result = self.agent(Script(*[{"action": "list"}] * 5), max_steps=3).run()
        self.assertEqual(result["steps"], 3)
        self.assertIn("سقف", result["summary"])
        flag = {"stop": False}

        class Stopper(Script):
            def chat_stream(s, messages, system, *a, **k):
                reply = super().chat_stream(messages, system, *a, **k)
                if system != aa.PLAN_PROMPT:
                    flag["stop"] = True
                return reply
        result = self.agent(Stopper({"action": "list"}, {"action": "list"}), should_stop=lambda: flag["stop"]).run()
        self.assertTrue(result["stopped"])
        self.assertTrue(result["zip"].exists())

    def test_external_edit_of_the_original_is_reported(self):
        class Meddler(Script):
            def chat_stream(s, *a, **k):
                (self.proj / "calc.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
                return super().chat_stream(*a, **k)
        result = self.agent(Meddler({"action": "finish", "summary": "x"})).run()
        self.assertEqual(result["external"], ["calc.py"])
        self.assertIn("هشدار", self.zip_text(result, "AI1CODE_REPORT.md"))

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
        self.assertIn("SYNTAX ERROR in calc.py line 1", router.seen[1][-1])
        self.assertIn("INVALID JSON", router.seen[2][-1])
        self.assertTrue(any("SYNTAX ERROR" in e for e in self.events))

    def test_finish_is_held_back_once_until_a_check_passed_after_the_last_edit(self):
        router = Script({"action": "replace", "path": "calc.py", "old": "a - b", "new": "a + b"},
                        {"action": "finish", "summary": "done"},                               # too early
                        {"action": "run", "args": ["python", "-m", "unittest"]},
                        {"action": "review"},
                        {"action": "finish", "summary": "done, tests pass"})
        result = self.agent(router).run()
        self.assertIn("GATE", router.seen[2][-1])
        self.assertEqual(result["summary"], "done, tests pass")
        self.assertEqual(result["runs"][0][1], 0)

    def test_gate_requires_a_check_and_a_clean_review_after_a_change(self):
        router = Script({"action": "write", "path": "new.txt", "content": "x"},
                        {"action": "finish", "summary": "a"},                                  # too early
                        {"action": "run", "args": ["python", "-m", "compileall", "-q", "."]},
                        {"action": "review"},
                        {"action": "finish", "summary": "final"})
        result = self.agent(router).run()
        self.assertIn("GATE", router.seen[2][-1])                                              # the check gate spoke
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
        self.assertIn("read-only", router.seen[2][-1])
        self.assertIn("read-only", router.seen[3][-1])
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
        self.assertEqual(result["summary"], "blocked")
        self.assertEqual(result["changed"], [])                # nothing was written to the working copy
        self.assertEqual(result["runs"], [])                   # no process ran: neither python nor PowerShell
        self.assertEqual(approved, [])                         # shell / folder-delete approvals were never even asked
        self.assertEqual(denied, ["map", "write", "run", "shell", "delete"])
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
        self.assertIn("بررسی", result["summary"])
        self.assertTrue(result["zip"].exists())                 # an honest report is still delivered
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

    def test_working_copy_is_removed_when_the_mission_raises(self):
        parent = Path(self.tmp.name) / "temp-work"
        class Boom(Script):
            def chat_stream(self, *a, **k):
                raise RuntimeError("model exploded")
        with mock.patch.object(aa.tempfile, "mkdtemp", return_value=str(parent)):
            with self.assertRaises(RuntimeError):
                self.agent(Boom()).run()
        self.assertFalse(parent.exists())

    def test_snapshot_skips_unreadable_files_instead_of_crashing(self):
        with mock.patch.object(aa.Path, "read_bytes", side_effect=OSError("access denied")):
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


if __name__ == "__main__":
    unittest.main()
