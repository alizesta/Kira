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
    def test_main_window_defers_controller_imports_to_registry_factories(self):
        source = (ROOT / "kira" / "ui" / "main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eager = [
            node.module for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module and node.module.startswith("main_window_")
        ]
        self.assertEqual(eager, [])
        self.assertIn("lazy_factories=True", source)
        self.assertIn("import_module", source)

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


    def test_workers_module_defers_search_attachment_and_provider_imports(self):
        source = (ROOT / "kira" / "ui" / "workers.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eager = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported = {alias.name for alias in node.names}
                if module.endswith("hybrid_ai") or module.endswith("websearch") or "attachments" in imported:
                    eager.append((module, sorted(imported)))
            elif isinstance(node, ast.Import):
                eager.extend(
                    (alias.name, [])
                    for alias in node.names
                    if alias.name in {"kira.hybrid_ai", "kira.websearch", "kira.chat.attachments"}
                )
        self.assertEqual(eager, [])

        attach_worker = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "AttachWorker"
        )
        attach_run = next(
            node for node in attach_worker.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        parser_imports = [
            node for node in ast.walk(attach_run)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("chat.attachment_content")
        ]
        self.assertTrue(
            any({alias.name for alias in node.names} >= {"AttachmentError", "load_attachment"}
                for node in parser_imports),
            "AttachWorker must lazily import the Qt-free attachment content parser",
        )

    def test_eager_shell_modules_do_not_import_worker_implementations(self):
        paths = (
            "kira/ui/application_adapters.py",
            "kira/ui/main_window_chat_support.py",
            "kira/ui/main_window_voice_settings_support.py",
            "kira/ui/main_window_lifecycle_support.py",
            "kira/ui/main_window_root_support.py",
        )
        for relative in paths:
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            eager = [
                node for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("workers")
            ]
            self.assertEqual(eager, [], relative)

    def test_worker_classes_are_imported_only_inside_feature_actions(self):
        expectations = {
            "kira/ui/application_adapters.py": "StreamWorker",
            "kira/ui/main_window_chat.py": "SearchWorker",
            "kira/ui/main_window_voice_settings.py": "TaskWorker",
            "kira/ui/main_window_lifecycle.py": "OllamaTaskWorker",
            "kira/ui/main_window_composition.py": "AttachWorker",
        }
        for relative, class_name in expectations.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imports = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("workers")
                and any(alias.name == class_name for alias in node.names)
            ]
            self.assertTrue(imports, f"{relative} must retain a lazy {class_name} import")
            top_level = [
                node for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("workers")
            ]
            self.assertEqual(top_level, [], relative)

        # Removing a worker from a support module must also remove every old
        # re-export import that would fail when the lazy worker is first used.
        forbidden_support_imports = {
            "kira/ui/main_window_composition.py": (
                "main_window_root_support", {"AttachWorker"}
            ),
            "kira/ui/main_window_chat.py": (
                "main_window_chat_support", {"SearchWorker", "TaskWorker"}
            ),
        }
        for relative, (support_module, forbidden_names) in forbidden_support_imports.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            stale = [
                node for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith(support_module)
                and forbidden_names.intersection(alias.name for alias in node.names)
            ]
            self.assertEqual(stale, [], relative)


    def test_importing_window_composition_does_not_import_feature_support_graph(self):
        code = """
import importlib
import sys
importlib.import_module("kira.ui.main_window_composition")
forbidden = {
    "kira.ui.main_window_root_support",
    "kira.game_mode",
    "kira.desktop_capture",
    "kira.companion",
    "kira.emotion.backend_png",
    "kira.voice",
}
loaded = forbidden.intersection(sys.modules)
assert not loaded, sorted(loaded)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_bootstrap_defers_window_composition_until_after_window_and_modules(self):
        source = (ROOT / "kira" / "ui" / "bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        run = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_application"
        )
        imports = [
            node for node in ast.walk(run)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("main_window_composition")
        ]
        self.assertEqual(len(imports), 1)
        window_line = next(
            node.lineno for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "MainWindow"
        )
        registration_line = next(
            node.lineno for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register_application_modules"
        )
        self.assertGreater(imports[0].lineno, window_line)
        self.assertGreater(imports[0].lineno, registration_line)

    def test_root_window_support_does_not_eagerly_import_game_capture(self):
        source = (ROOT / "kira" / "ui" / "main_window_root_support.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [
            node.module for node in tree.body
            if isinstance(node, ast.ImportFrom)
        ]
        self.assertNotIn("..game_mode", imports)



    def test_monitor_menu_does_not_realize_capture_during_window_composition(self):
        source = (ROOT / "kira" / "ui" / "main_window_composition.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "for monitor in self.adapters.game_mode.capture_service.list_monitors()",
            source,
        )
        self.assertIn(
            "desktop_vision_monitor_menu.aboutToShow.connect",
            source,
        )
        self.assertIn(
            "_populate_desktop_monitor_menu",
            source,
        )



if __name__ == "__main__":
    unittest.main()
