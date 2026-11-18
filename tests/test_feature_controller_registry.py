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

    def test_missing_feature_attribute_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            self.registry.resolve("not_a_feature_method")

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

    def test_composition_injects_attachment_workflow_into_chat_controller(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira/ui/main_window_composition.py").read_text(encoding="utf-8")
        self.assertIn(
            'self._controller_registry.get("chat").bind_attachment_controller(',
            source,
        )


if __name__ == "__main__":
    unittest.main()
