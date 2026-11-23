"""Regression coverage for deferred desktop startup dependencies."""
from __future__ import annotations

import ast
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

from kira.lazy_tool_agent import LazyToolAgent
from kira.think_filter import ThinkFilter


ROOT = Path(__file__).resolve().parents[1]


class _Tasks:
    def active(self, session_id=None):
        return session_id


class _FakeToolAgent:
    def __init__(self):
        self.tasks = _Tasks()
        self.settings = None
        self.competitive_safe = False
        self.cancelled = False
        self.begun = []

    def set_settings(self, settings):
        self.settings = settings

    def set_competitive_safe_mode(self, enabled):
        self.competitive_safe = bool(enabled)

    def begin_turn(self, session_id=None):
        self.begun.append(session_id)

    def plan(self, text, session_id=None):
        return (text, session_id)

    def has_new_pending_confirmation(self, session_id=None):
        return False

    def handle_confirmation_reply(self, text, session_id=None):
        return None

    def handle_task_command(self, text, session_id=None):
        return None

    def control_running(self, text, session_id=None):
        return None

    def is_task_running(self, session_id=None):
        return False

    def request_cancel(self, session_id=None):
        self.cancelled = True
        return True

    def clear_session(self, session_id=None):
        return session_id

    def release_session(self, session_id):
        return True


class LazyToolAgentTests(unittest.TestCase):
    def test_constructor_and_cleanup_do_not_create_agent(self):
        created = []
        lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1])

        self.assertEqual(created, [])
        self.assertIsNotNone(lazy.tasks)
        self.assertFalse(lazy.request_cancel())
        self.assertFalse(lazy.release_session("kira"))
        self.assertEqual(created, [])

    def test_normal_chat_and_idle_callbacks_do_not_create_agent(self):
        created = []
        lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1])
        lazy.set_settings({"tools_mode": "auto"})
        lazy.begin_turn("kira")

        self.assertIsNone(lazy.plan("سلام، حالت چطوره؟", session_id="kira"))
        self.assertIsNone(lazy.tasks.active("kira"))
        self.assertFalse(lazy.is_task_running("kira"))
        self.assertEqual(created, [])

    def test_first_actionable_request_creates_agent_once_and_applies_pending_state(self):
        created = []
        lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1])
        settings = {"tools_mode": "always"}
        lazy.set_settings(settings)
        lazy.set_competitive_safe_mode(False)
        lazy.begin_turn("kira")

        result = lazy.plan("ساعت چنده؟", session_id="kira")
        self.assertEqual(result, ("ساعت چنده؟", "kira"))
        self.assertEqual(len(created), 1)
        self.assertIs(created[0].settings, settings)
        self.assertEqual(created[0].begun, ["kira"])
        self.assertEqual(lazy.tasks.active("mika"), "mika")
        self.assertEqual(len(created), 1)

    def test_unknown_but_actionable_request_still_enters_lazy_triage(self):
        created = []
        lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1])
        lazy.set_settings({"tools_mode": "auto"})

        result = lazy.plan("یه قابلیت ناشناخته رو برام اعمال کن", session_id="kira")
        self.assertEqual(result, ("یه قابلیت ناشناخته رو برام اعمال کن", "kira"))
        self.assertEqual(len(created), 1)

    def test_command_dispatch_probes_pending_task_without_eager_tools_on_idle_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            lazy = LazyToolAgent(lambda: _FakeToolAgent(), data_dir=Path(directory))
            lazy.set_settings({"tools_mode": "auto", "agent_planning": "auto"})
            self.assertTrue(lazy.enabled())
            self.assertTrue(lazy.planning_enabled())
            self.assertIsNone(lazy.tasks.active("kira"))
            self.assertFalse(lazy.prepare_control_dispatch("ادامه بده", session_id="kira"))
            self.assertFalse(lazy.realized)

    def test_persisted_task_is_realized_only_for_its_own_character(self):
        from kira.tools.tasks import TaskStore, P_WAIT_USER

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            plan = store.new("ادامه کار", session_id="ren")
            plan.status = P_WAIT_USER
            store.save()

            created = []
            lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1], data_dir=Path(directory))
            lazy.set_settings({"tools_mode": "auto"})
            self.assertIsNone(lazy.plan("جواب سؤال قبلی", session_id="kira"))
            self.assertFalse(lazy.realized)
            result = lazy.plan("این مسیر را انتخاب کن", session_id="ren")
            self.assertEqual(result, ("این مسیر را انتخاب کن", "ren"))
            self.assertEqual(len(created), 1)

    def test_runtime_updates_and_cleanup_delegate_after_creation(self):
        instance = _FakeToolAgent()
        lazy = LazyToolAgent(lambda: instance)
        lazy.set_settings({"tools_mode": "always"})
        lazy.plan("ساعت چنده؟", session_id="kira")
        settings = {"tools_mode": "always"}
        lazy.set_settings(settings)
        lazy.set_competitive_safe_mode(False)
        self.assertTrue(lazy.request_cancel("kira"))
        self.assertEqual(lazy.clear_session("kira"), "kira")
        self.assertTrue(lazy.release_session("kira"))
        self.assertIs(instance.settings, settings)
        self.assertFalse(instance.competitive_safe)
        self.assertTrue(instance.cancelled)


class ThinkFilterTests(unittest.TestCase):
    def test_reasoning_tags_split_across_stream_chunks_are_removed(self):
        stream = ThinkFilter()
        visible = "".join(
            stream.feed(chunk)
            for chunk in ("hello<thi", "nk>private</thi", "nk>world")
        )
        self.assertEqual(visible + stream.flush(), "helloworld")

    def test_incomplete_reasoning_block_is_discarded_on_flush(self):
        stream = ThinkFilter()
        visible = stream.feed("visible<think>private but unfinished")
        self.assertEqual(visible, "visible")
        self.assertEqual(stream.flush(), "")

    def test_incomplete_open_tag_is_preserved_when_not_a_reasoning_block(self):
        stream = ThinkFilter()
        self.assertEqual(stream.feed("visible<thi"), "visible")
        self.assertEqual(stream.flush(), "<thi")


class StartupImportBoundaryTests(unittest.TestCase):
    def test_tool_protocol_does_not_import_hybrid_ai(self):
        source = (ROOT / "kira" / "tools" / "protocol.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        self.assertNotIn("hybrid_ai", imports)
        self.assertIn("think_filter", imports)

    def test_root_window_support_does_not_import_tool_agent(self):
        source = (ROOT / "kira" / "ui" / "main_window_root_support.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported = {alias.name for alias in node.names}
            self.assertNotIn("ToolAgent", imported)

    def test_importing_tool_protocol_does_not_load_agent_or_provider_stack(self):
        code = (
            "import sys; import kira.tools.protocol; "
            "forbidden = {'kira.tools.agent', 'kira.tools.builtin', "
            "'kira.tools.appcatalog', 'kira.hybrid_ai', 'kira.hybrid_providers'}; "
            "loaded = forbidden.intersection(sys.modules); "
            "assert not loaded, sorted(loaded)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_bootstrap_keeps_tool_agent_import_inside_lazy_factory(self):
        source = (ROOT / "kira" / "ui" / "bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        eager_tool_imports = [
            node for node in module_imports
            if isinstance(node, ast.ImportFrom)
            and node.module and node.module.endswith("tools")
        ]
        self.assertEqual(eager_tool_imports, [])
        factory = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_create_tool_agent"
        )
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.module.endswith("tools")
                            for node in ast.walk(factory)))


if __name__ == "__main__":
    unittest.main()
