"""Tests for scoped dependencies across composed MainWindow feature controllers."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "kira" / "ui"


class MainWindowFeatureDependencyTests(unittest.TestCase):
    FEATURES = {
        "main_window_attachments_vision.py": "attachments_vision",
        "main_window_character_settings.py": "character_settings",
        "main_window_chat.py": "chat",
        "main_window_lifecycle.py": "lifecycle",
        "main_window_provider_settings.py": "provider_settings",
        "main_window_runtime.py": "runtime",
        "main_window_session.py": "session",
        "main_window_voice_settings.py": "voice_settings",
    }

    MAIN_WINDOW_BASES = ["QMainWindow"]
    FEATURE_CONTROLLERS = (
        "RuntimeController", "ChatController", "AttachmentsVisionController",
        "LifecycleController", "ProviderSettingsController",
        "CharacterSettingsController", "VoiceSettingsController", "SessionController",
    )

    def test_each_feature_controller_uses_its_scoped_dependency_module(self):
        for filename, feature in self.FEATURES.items():
            source = (UI / filename).read_text(encoding="utf-8")
            self.assertIn(
                f"from .main_window_{feature}_support import",
                source,
                filename,
            )
            self.assertNotIn("from .main_window_support import *", source, filename)

    def test_root_dependencies_are_owned_by_composition_not_the_host(self):
        composition = (UI / "main_window_composition.py").read_text(encoding="utf-8")
        host = (UI / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("from .main_window_root_support import (", composition)
        self.assertNotIn("main_window_root_support", host)

    def test_main_window_shell_composes_all_eight_feature_controllers(self):
        source = (UI / "main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="main_window.py")
        main_window = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        bases = [
            node.id if isinstance(node, ast.Name) else node.attr
            for node in main_window.bases
        ]
        self.assertEqual(bases, self.MAIN_WINDOW_BASES)
        source_text = (UI / "main_window.py").read_text(encoding="utf-8")
        for controller in self.FEATURE_CONTROLLERS:
            self.assertIn(controller, source_text)

    def test_main_window_host_contains_no_feature_behavior(self):
        source = (UI / "main_window.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="main_window.py")
        main_window = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        methods = {
            node.name for node in main_window.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(methods, {
            "__init__", "_dispatch_qt_event",
            "showEvent", "hideEvent", "changeEvent", "resizeEvent",
            "closeEvent", "dragEnterEvent", "dropEvent",
        })
        self.assertNotIn("__getattr__", methods)

    def test_feature_controller_uses_only_the_explicit_presentation_context(self):
        from PySide6.QtCore import QObject

        from kira.ui.feature_controller_registry import FeatureControllerRegistry
        from kira.ui.window_feature_controller import WindowFeatureController
        from kira.ui.window_presentation_context import WindowPresentationContext

        window = QObject()
        window.presentation_context = WindowPresentationContext(window, FeatureControllerRegistry({}))
        controller = WindowFeatureController(window)

        window.presentation_context.state._closing = False
        self.assertFalse(controller.context.state._closing)
        controller.counter = 2
        self.assertEqual(controller.counter, 2)
        self.assertFalse(hasattr(window, "counter"))
        with self.assertRaises(AttributeError):
            _ = controller.undeclared_window_attribute
        with self.assertRaises(AttributeError):
            controller.context.state.undeclared = True
        self.assertNotIn("__getattr__", WindowFeatureController.__dict__)
        self.assertNotIn("__setattr__", WindowFeatureController.__dict__)
        self.assertIs(controller.window, window)
        self.assertIs(controller.parent(), window)

    def test_presentation_context_has_strict_namespaces_and_front_only_views(self):
        from PySide6.QtCore import QObject

        from kira.chat_sessions import NOOP
        from kira.ui.feature_controller_registry import FeatureControllerRegistry
        from kira.ui.window_presentation_context import WindowPresentationContext

        window = QObject()
        context = WindowPresentationContext(window, FeatureControllerRegistry({}))
        front = object()
        context.state.cur = front
        context.state.front = front
        status = object()
        context.views.status = status
        self.assertIs(context.views.status, status)

        context.state.cur = object()
        self.assertIs(context.views.status, NOOP)

        with self.assertRaises(AttributeError):
            context.views.not_a_declared_widget = object()
        with self.assertRaises(AttributeError):
            _ = context.services.not_a_service

    def test_shell_forwards_qt_virtual_events_to_their_feature_owners(self):
        source = (UI / "main_window.py").read_text(encoding="utf-8")
        expected_routes = (
            '_dispatch_qt_event("lifecycle", "showEvent", event)',
            '_dispatch_qt_event("lifecycle", "hideEvent", event)',
            '_dispatch_qt_event("lifecycle", "changeEvent", event)',
            '_dispatch_qt_event("session", "resizeEvent", event)',
            '_dispatch_qt_event("runtime", "closeEvent", event)',
            '_dispatch_qt_event("attachments_vision", "dragEnterEvent", event)',
            '_dispatch_qt_event("attachments_vision", "dropEvent", event)',
        )
        for route in expected_routes:
            self.assertIn(route, source)

    def test_shared_support_contains_only_cross_feature_helpers_and_relays(self):
        source = (UI / "main_window_support.py").read_text(encoding="utf-8")
        forbidden = (
            "from ..hybrid_ai import",
            "from ..voice import",
            "from ..listener import",
            "from ..vision_pipeline import",
            "from .. import routes",
            "from .. import websearch",
            "from ..tools import",
            "from ..chat.application_service import",
        )
        for dependency in forbidden:
            self.assertNotIn(dependency, source)
        self.assertIn("class SessionRelay", source)
        self.assertIn("def front_only", source)
        self.assertIn("def load_reactions", source)

    def test_context_resource_lookup_is_allowlisted_and_owner_aware(self):
        from types import SimpleNamespace

        from PySide6.QtCore import QObject

        from kira.ui.feature_controller_registry import FeatureControllerRegistry
        from kira.ui.window_presentation_context import WindowPresentationContext

        window = QObject()
        context = WindowPresentationContext(window, FeatureControllerRegistry({}))
        worker = object()
        audio = object()
        vision_worker = object()
        context.state._api_worker = worker
        context.adapters.game_audio_listener = audio
        context.state.cur = SimpleNamespace(_vision_worker=vision_worker)

        self.assertIs(context.resource("_api_worker"), worker)
        self.assertIs(context.resource("game_audio_listener"), audio)
        self.assertIs(context.resource("_vision_worker"), vision_worker)
        self.assertIsNone(context.resource("not_a_registered_resource"))

    def test_shutdown_tracks_vision_workers_for_every_session(self):
        runtime = (UI / "main_window_runtime.py").read_text(encoding="utf-8")
        application = (ROOT / "kira" / "app" / "session_application.py").read_text(encoding="utf-8")

        self.assertIn('getattr(session, "_vision_worker", None)', runtime)
        self.assertIn("vision_worker.cancel_request()", runtime)
        self.assertIn("(sess.worker, sess._search_worker, sess._vision_worker)", runtime)
        self.assertIn('getattr(session, "_vision_session", None) is session', application)
        self.assertNotIn("vision_session=vision_session", application)
        self.assertNotIn("vision_worker=vision_worker", application)

    def test_session_relay_uses_explicit_context_and_controller_owners(self):
        source = (UI / "main_window_support.py").read_text(encoding="utf-8")
        self.assertIn("super().__init__(context.host)", source)
        self.assertIn("self.context.controllers.require(owner)", source)
        self.assertIn("self.context.services.chat_application_service.handle_provider_event", source)
        self.assertIn("context.is_background_session", source)
        self.assertNotIn("getattr(self.w", source)
        self.assertNotIn("self.cur is not self.front", source)

    def test_feature_support_modules_do_not_import_other_feature_controllers(self):
        for path in UI.glob("main_window_*_support.py"):
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                if line.startswith("from .main_window_"):
                    self.assertEqual(
                        line,
                        "from .main_window_support import " + line.split(" import ", 1)[1],
                        str(path),
                    )

    def test_every_feature_support_module_exists(self):
        for feature in self.FEATURES.values():
            self.assertTrue(
                (UI / f"main_window_{feature}_support.py").is_file(),
                feature,
            )


    def test_controller_context_references_match_declared_namespace_contracts(self):
        import re

        context_source = (UI / "window_presentation_context.py").read_text(encoding="utf-8")
        namespaces = {
            "state": "STATE_FIELDS",
            "services": "SERVICE_FIELDS",
            "adapters": "ADAPTER_FIELDS",
            "views": "VIEW_FIELDS",
        }
        allowed = {}
        for namespace, constant in namespaces.items():
            match = re.search(
                rf"{constant}\\s*=\\s*frozenset\\(\\{{([\\s\\S]*?)\\}}\\)",
                context_source,
            )
            self.assertIsNotNone(match, constant)
            allowed[namespace] = set(re.findall(r'"([^"]+)"', match.group(1)))

        for filename in self.FEATURES:
            source = (UI / filename).read_text(encoding="utf-8")
            for namespace, fields in allowed.items():
                referenced = set(re.findall(
                    rf"self\\.context\\.{namespace}\\.([A-Za-z_]\\w*)",
                    source,
                ))
                self.assertLessEqual(
                    referenced,
                    fields,
                    f"{filename} references undeclared {namespace} fields: {sorted(referenced - fields)}",
                )

        composition = (UI / "main_window_composition.py").read_text(encoding="utf-8")
        for namespace, fields in allowed.items():
            referenced = set(re.findall(
                rf"self\\.{namespace}\\.([A-Za-z_]\\w*)",
                composition,
            ))
            self.assertLessEqual(
                referenced,
                fields,
                f"composition references undeclared {namespace} fields: {sorted(referenced - fields)}",
            )

    def test_resource_owner_map_resolves_only_declared_context_resources(self):
        from kira.chat_sessions import SESSION_FIELDS
        from kira.ui.window_presentation_context import (
            ADAPTER_FIELDS,
            RESOURCE_OWNERS,
            SERVICE_FIELDS,
            STATE_FIELDS,
            VIEW_FIELDS,
        )

        namespaces = {
            "state": STATE_FIELDS,
            "services": SERVICE_FIELDS,
            "adapters": ADAPTER_FIELDS,
            "views": VIEW_FIELDS,
            "session": frozenset(SESSION_FIELDS),
        }
        context_resources = {"listener", "stopping_listener"}
        controller_resources = {"_attach_worker"}

        for resource, (namespace, field) in RESOURCE_OWNERS.items():
            if namespace in namespaces:
                self.assertIn(field, namespaces[namespace], resource)
            elif namespace == "context":
                self.assertIn(field, context_resources, resource)
            elif namespace == "session_controller":
                self.assertIn(field, controller_resources, resource)
            else:
                self.fail(f"{resource} has an unknown resource owner: {namespace}")



if __name__ == "__main__":
    unittest.main()
