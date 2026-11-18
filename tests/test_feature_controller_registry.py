"""Contract tests for explicit feature-controller ownership and dispatch."""
import ast
from pathlib import Path
import unittest

from kira.ui.feature_controller_registry import FeatureControllerRegistry


class FirstController:
    def shared_action(self):
        return "first"


class SecondController:
    def shared_action(self):
        return "second"

    def unique_action(self):
        return "unique"


class FeatureControllerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.first = FirstController()
        self.second = SecondController()
        self.registry = FeatureControllerRegistry({
            "first": self.first,
            "second": self.second,
        })

    def test_resolves_methods_in_declared_controller_order(self):
        self.assertEqual(self.registry.resolve("shared_action")(), "first")
        self.assertEqual(self.registry.resolve("unique_action")(), "unique")

    def test_reports_all_owners_of_legacy_collisions(self):
        self.assertEqual(
            self.registry.owners_for("shared_action"),
            ("first", "second"),
        )
        self.assertEqual(self.registry.owners_for("unique_action"), ("second",))
        self.assertEqual(self.registry.owners_for("missing"), ())

    def test_dispatches_events_to_the_declared_feature_owner(self):
        class EventController:
            def closeEvent(self, event):
                return ("closed", event)

        registry = FeatureControllerRegistry({"runtime": EventController()})
        marker = object()
        self.assertEqual(
            registry.dispatch_event(object(), "runtime", "closeEvent", marker),
            ("closed", marker),
        )

    def test_qt_event_owner_is_enforced(self):
        registry = FeatureControllerRegistry({"session": self.second})
        with self.assertRaises(ValueError):
            registry.dispatch_event(object(), "session", "closeEvent", object())

    def test_registry_membership_is_immutable_after_construction(self):
        controllers = {"first": self.first}
        registry = FeatureControllerRegistry(controllers)
        controllers["second"] = self.second
        self.assertIsNone(registry.get("second"))
        self.assertIs(registry.require("first"), self.first)

    def test_require_reports_missing_peer_as_lookup_error(self):
        with self.assertRaisesRegex(LookupError, "missing"):
            self.registry.require("missing")

    def test_missing_feature_attribute_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            self.registry.resolve("not_a_feature_method")

    def test_controller_peer_lookup_uses_the_explicit_registry(self):
        from PySide6.QtCore import QObject

        from kira.ui.window_feature_controller import WindowFeatureController

        class Registry:
            def get(self, feature):
                return self.second if feature == "second" else None

            second = object()

        window = QObject()
        window._controller_registry = Registry()
        controller = WindowFeatureController(window)
        self.assertIs(controller.feature_controller("second"), window._controller_registry.second)
        with self.assertRaises(LookupError):
            controller.feature_controller("missing")

    def test_chat_controller_uses_injected_attachment_workflow(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        chat = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ChatController"
        )
        methods = {
            node.name: node for node in chat.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("bind_attachment_controller", methods)
        self.assertIn("attachment_controller", methods)
        chat_source = ast.get_source_segment(source, chat)
        for legacy_call in (
            "self.attach_loading(",
            "self.clear_attachments(",
            "self.show_attach_error(",
            "self._tiles",
        ):
            self.assertNotIn(legacy_call, chat_source)

    def test_chat_uses_explicit_peer_controller_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        chat = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.ClassDef) and node.name == "ChatController"
        )
        chat_source = ast.get_source_segment(source, chat)
        for method in (
            "_as", "add_chat", "on_stream_chunk", "on_stream_done",
            "on_error", "_ensure_session_conversation",
            "_send_pending_for_session", "_game_vision_attachment",
            "safe_stop_speaker", "save_message", "reply_local",
            "set_status", "set_badge", "show_upload_tiles",
            "finish_request", "_send_next_pending", "body_active",
            "active_character", "_stream_begin", "refresh_tab_buttons",
        ):
            self.assertNotIn("self." + method + "(", chat_source, method)
        self.assertIn('self.feature_controller("session")', chat_source)
        self.assertIn('self.feature_controller("runtime")', chat_source)
        self.assertIn('self.feature_controller("attachments_vision")', chat_source)

    def test_feature_controllers_do_not_call_peer_methods_through_window_proxy(self):
        root = Path(__file__).resolve().parents[1]
        filenames = (
            "main_window_attachments_vision.py",
            "main_window_character_settings.py",
            "main_window_chat.py",
            "main_window_lifecycle.py",
            "main_window_provider_settings.py",
            "main_window_runtime.py",
            "main_window_session.py",
            "main_window_voice_settings.py",
        )
        trees = {
            name: ast.parse((root / "kira/ui" / name).read_text(encoding="utf-8"))
            for name in filenames
        }
        methods_by_file = {}
        owners = {}
        for name, tree in trees.items():
            controller = next(
                node for node in tree.body if isinstance(node, ast.ClassDef)
            )
            methods = {
                node.name for node in controller.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            methods_by_file[name] = methods
            for method in methods:
                owners.setdefault(method, set()).add(name)

        violations = []
        for name, tree in trees.items():
            controller = next(
                node for node in tree.body if isinstance(node, ast.ClassDef)
            )
            for node in ast.walk(controller):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                ):
                    continue
                peer_owners = owners.get(func.attr, set()) - {name}
                if peer_owners and func.attr not in methods_by_file[name]:
                    violations.append((name, func.attr, sorted(peer_owners)))
        self.assertEqual(violations, [])

    def test_composition_injects_attachment_workflow_into_chat_controller(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira/ui/main_window_composition.py").read_text(encoding="utf-8")
        self.assertIn(
            'self._controller_registry.get("chat").bind_attachment_controller(',
            source,
        )


if __name__ == "__main__":
    unittest.main()
