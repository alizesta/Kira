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

    def test_controller_peer_lookup_uses_the_explicit_registry(self):
        from PySide6.QtCore import QObject

        from kira.ui.window_feature_controller import WindowFeatureController

        from kira.ui.window_presentation_context import WindowPresentationContext

        window = QObject()
        controller = WindowFeatureController(window)
        second = object()
        registry = FeatureControllerRegistry({"chat": controller, "session": second})
        window.presentation_context = WindowPresentationContext(window, registry)
        self.assertIs(controller.feature_controller("session"), second)
        with self.assertRaises(PermissionError):
            controller.feature_controller("missing")
        with self.assertRaises(PermissionError):
            controller.feature_controller("lifecycle")


    def test_controller_context_is_scoped_to_its_declared_capabilities(self):
        from PySide6.QtCore import QObject
        from kira.ui.window_feature_controller import WindowFeatureController
        from kira.ui.window_presentation_context import WindowPresentationContext

        window = QObject()
        chat = WindowFeatureController(window)
        session = object()
        registry = FeatureControllerRegistry({"chat": chat, "session": session})
        root = WindowPresentationContext(window, registry)
        window.presentation_context = root
        scoped = chat.context

        self.assertIn("chat_application_service", scoped.services._allowed)
        self.assertNotIn("ollama_client", scoped.services._allowed)
        self.assertIn("input", scoped.views._allowed)
        self.assertNotIn("route_list", scoped.views._allowed)
        self.assertNotIn("host", dir(scoped))
        self.assertNotIn("controllers", dir(scoped))
        self.assertIs(scoped.require_peer("session"), session)
        with self.assertRaises(AttributeError):
            _ = scoped.services.ollama_client
        with self.assertRaises(AttributeError):
            _ = scoped.views.route_list
        with self.assertRaises(AttributeError):
            _ = scoped.host
        with self.assertRaises(PermissionError):
            scoped.require_peer("lifecycle")
        with self.assertRaises(PermissionError):
            scoped.resource("_route_worker")

    def test_every_controller_scope_is_a_subset_of_root_context_contracts(self):
        from kira.ui.window_presentation_context import (
            ADAPTER_FIELDS, CONTROLLER_ACCESS, SERVICE_FIELDS, STATE_FIELDS, VIEW_FIELDS,
        )
        roots = {
            "state": STATE_FIELDS,
            "services": SERVICE_FIELDS,
            "adapters": ADAPTER_FIELDS,
            "views": VIEW_FIELDS,
        }
        self.assertEqual(
            set(CONTROLLER_ACCESS),
            {"runtime", "chat", "session", "lifecycle", "attachments_vision",
             "provider_settings", "character_settings", "voice_settings"},
        )
        for feature, access in CONTROLLER_ACCESS.items():
            for namespace, root_fields in roots.items():
                self.assertTrue(
                    access[namespace].issubset(root_fields),
                    f"{feature}.{namespace} contains fields outside the root contract",
                )

    def test_controller_source_access_matches_capability_matrix(self):
        from kira.ui.window_presentation_context import CONTROLLER_ACCESS
        root = Path(__file__).resolve().parents[1]
        filenames = {
            "runtime": "main_window_runtime.py",
            "chat": "main_window_chat.py",
            "session": "main_window_session.py",
            "lifecycle": "main_window_lifecycle.py",
            "attachments_vision": "main_window_attachments_vision.py",
            "provider_settings": "main_window_provider_settings.py",
            "character_settings": "main_window_character_settings.py",
            "voice_settings": "main_window_voice_settings.py",
        }
        violations = []
        for feature, filename in filenames.items():
            source = (root / "kira/ui" / filename).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filename)
            access = CONTROLLER_ACCESS[feature]
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                    base = node.value
                    if (isinstance(base.value, ast.Attribute)
                            and isinstance(base.value.value, ast.Name)
                            and base.value.value.id == "self"
                            and base.value.attr == "context"
                            and base.attr in {"state", "services", "adapters", "views"}
                            and node.attr not in access[base.attr]):
                        violations.append(f"{feature}:{node.lineno}:{base.attr}.{node.attr}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if (node.func.attr == "feature_controller" and node.args
                            and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value not in access["peers"]):
                        violations.append(f"{feature}:{node.lineno}:peer.{node.args[0].value}")
                    if (node.func.attr == "resource" and node.args
                            and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value not in access["resources"]):
                        violations.append(f"{feature}:{node.lineno}:resource.{node.args[0].value}")
        self.assertEqual(violations, [])

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
            'self.controllers.require("chat").bind_attachment_controller(',
            source,
        )


if __name__ == "__main__":
    unittest.main()
