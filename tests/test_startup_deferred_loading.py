"""Regression coverage for deferred desktop startup dependencies."""
from __future__ import annotations

import ast
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

    def set_settings(self, settings):
        self.settings = settings

    def set_competitive_safe_mode(self, enabled):
        self.competitive_safe = bool(enabled)

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
        self.assertIsNone(lazy.clear_session("kira"))
        self.assertEqual(created, [])

    def test_first_capability_use_creates_agent_once_and_applies_pending_state(self):
        created = []
        lazy = LazyToolAgent(lambda: created.append(_FakeToolAgent()) or created[-1])
        settings = {"tools_mode": "off"}
        lazy.set_settings(settings)
        lazy.set_competitive_safe_mode(True)

        self.assertFalse(lazy.is_task_running("kira"))
        self.assertEqual(len(created), 1)
        self.assertIs(created[0].settings, settings)
        self.assertTrue(created[0].competitive_safe)
        self.assertEqual(lazy.tasks.active("mika"), "mika")
        self.assertEqual(len(created), 1)

    def test_runtime_updates_and_cleanup_delegate_after_creation(self):
        instance = _FakeToolAgent()
        lazy = LazyToolAgent(lambda: instance)
        lazy.is_task_running("kira")
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
