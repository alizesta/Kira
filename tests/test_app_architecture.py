import unittest

from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus


class EventBusTests(unittest.TestCase):
    def test_publish_notifies_subscribers(self):
        bus = EventBus()
        received = []
        bus.subscribe("chat.message.completed", lambda **event: received.append(event["text"]))
        bus.publish("chat.message.completed", text="hello")
        self.assertEqual(received, ["hello"])

    def test_unsubscribe_stops_notifications(self):
        bus = EventBus()
        received = []
        unsubscribe = bus.subscribe("voice.transcript", lambda **event: received.append(event["text"]))
        unsubscribe()
        bus.publish("voice.transcript", text="ignored")
        self.assertEqual(received, [])

    def test_publish_uses_snapshot_when_subscriber_changes_subscriptions(self):
        bus = EventBus()
        received = []
        unsubscribe = None

        def first(**_event):
            received.append("first")
            unsubscribe()

        unsubscribe = bus.subscribe("event", first)
        bus.subscribe("event", lambda **_event: received.append("second"))
        bus.publish("event")
        self.assertEqual(received, ["first", "second"])
        bus.publish("event")
        self.assertEqual(received, ["first", "second", "second"])


class DependencyContainerTests(unittest.TestCase):
    def test_factory_is_created_once_and_cached(self):
        container = DependencyContainer()
        calls = []
        container.register_factory("voice", lambda: calls.append("created") or object())
        first = container.resolve("voice")
        second = container.resolve("voice")
        self.assertIs(first, second)
        self.assertEqual(calls, ["created"])

    def test_instance_registration_replaces_factory(self):
        container = DependencyContainer()
        original = object()
        replacement = object()
        container.register_factory("chat", lambda: original)
        container.register_instance("chat", replacement)
        self.assertIs(container.resolve("chat"), replacement)

    def test_missing_dependency_raises_clear_error(self):
        with self.assertRaisesRegex(KeyError, "not registered"):
            DependencyContainer().resolve("missing")


class ModuleManagerTests(unittest.TestCase):
    class FakeModule:
        def __init__(self, name, events, fail_start=False):
            self.name = name
            self.events = events
            self.fail_start = fail_start

        def register(self, container, event_bus):
            self.events.append(("register", self.name))
            self.container = container
            self.event_bus = event_bus

        def start(self):
            self.events.append(("start", self.name))
            if self.fail_start:
                raise RuntimeError("intentional start failure")

        def stop(self):
            self.events.append(("stop", self.name))

        def dispose(self):
            self.events.append(("dispose", self.name))

    def test_dependencies_start_before_dependent_and_receive_shared_services(self):
        from kira.app.module_manager import ModuleManager, ModuleState

        events = []
        manager = ModuleManager()
        manager.register("memory", lambda: self.FakeModule("memory", events))
        manager.register(
            "chat",
            lambda: self.FakeModule("chat", events),
            dependencies=("memory",),
        )

        manager.start("chat")

        self.assertEqual(manager.state("memory"), ModuleState.STARTED)
        self.assertEqual(manager.state("chat"), ModuleState.STARTED)
        self.assertEqual(
            events,
            [
                ("register", "memory"),
                ("start", "memory"),
                ("register", "chat"),
                ("start", "chat"),
            ],
        )

    def test_active_dependents_prevent_unsafe_disable(self):
        from kira.app.module_manager import ModuleManager, ModuleManagerError

        events = []
        manager = ModuleManager()
        manager.register("memory", lambda: self.FakeModule("memory", events))
        manager.register(
            "chat",
            lambda: self.FakeModule("chat", events),
            dependencies=("memory",),
        )
        manager.start("chat")

        with self.assertRaisesRegex(ModuleManagerError, "Stop dependent"):
            manager.disable("memory")

    def test_disable_disposes_and_enable_recreates_module(self):
        from kira.app.module_manager import ModuleManager, ModuleState

        events = []
        created = []
        def factory():
            instance = self.FakeModule(f"feature-{len(created) + 1}", events)
            created.append(instance)
            return instance

        manager = ModuleManager()
        manager.register("feature", factory)
        manager.start("feature")
        manager.disable("feature")
        self.assertEqual(manager.state("feature"), ModuleState.DISABLED)
        manager.enable("feature")

        self.assertEqual(len(created), 2)
        self.assertEqual(manager.state("feature"), ModuleState.STARTED)
        self.assertIn(("dispose", "feature-1"), events)
        self.assertIn(("start", "feature-2"), events)

    def test_shutdown_disposes_a_module_that_was_stopped_earlier(self):
        from kira.app.module_manager import ModuleManager, ModuleState

        events = []
        manager = ModuleManager()
        manager.register("feature", lambda: self.FakeModule("feature", events))
        manager.start("feature")
        manager.stop("feature")

        errors = manager.shutdown()

        self.assertEqual(errors, {})
        self.assertEqual(events.count(("stop", "feature")), 1)
        self.assertEqual(events.count(("dispose", "feature")), 1)
        self.assertEqual(manager.state("feature"), ModuleState.DISPOSED)

    def test_optional_failure_does_not_block_independent_modules(self):
        from kira.app.module_manager import ModuleManager, ModuleState

        events = []
        manager = ModuleManager()
        manager.register(
            "broken",
            lambda: self.FakeModule("broken", events, fail_start=True),
            optional=True,
        )
        manager.register("healthy", lambda: self.FakeModule("healthy", events))

        states = manager.start_all()

        self.assertEqual(states["broken"], ModuleState.FAILED)
        self.assertEqual(states["healthy"], ModuleState.STARTED)
        self.assertIn("intentional start failure", manager.error("broken"))

    def test_dependency_cycles_fail_without_starting_modules(self):
        from kira.app.module_manager import ModuleManager, ModuleManagerError, ModuleState

        events = []
        manager = ModuleManager()
        manager.register("a", lambda: self.FakeModule("a", events), dependencies=("b",))
        manager.register("b", lambda: self.FakeModule("b", events), dependencies=("a",))

        with self.assertRaisesRegex(ModuleManagerError, "cycle"):
            manager.start("a")

        self.assertEqual(manager.state("a"), ModuleState.FAILED)
        self.assertEqual(manager.state("b"), ModuleState.FAILED)
        self.assertEqual(events, [])


class ApplicationServiceBoundaryTests(unittest.TestCase):
    def test_persona_memory_service_scopes_operations_by_character(self):
        from contextlib import nullcontext
        from unittest.mock import patch

        from kira.services.memory_service import PersonaMemoryService

        expected_items = [{"id": "ren-1", "group": "fact", "text": "prefers concise answers"}]
        service = PersonaMemoryService()
        with patch(
            "kira.services.memory_service.persona_memory.character_scope",
            return_value=nullcontext(),
        ) as scope, patch(
            "kira.services.memory_service.persona_memory.list_items",
            return_value=expected_items,
        ) as list_items:
            self.assertEqual(service.list_items("ren"), expected_items)

        scope.assert_called_once_with("ren")
        list_items.assert_called_once_with()

    def test_mood_service_delegates_current_and_reset(self):
        from unittest.mock import patch

        from kira.services.mood_service import MoodStateService

        current = {"emotion": "calm", "intensity": 20}
        service = MoodStateService()
        with patch("kira.services.mood_service.mood.current", return_value=current) as read:
            self.assertEqual(service.current(), current)
        with patch("kira.services.mood_service.mood.reset") as reset:
            service.reset()

        read.assert_called_once_with()
        reset.assert_called_once_with()


class ExtractedUiComponentTests(unittest.TestCase):
    def test_model_combo_is_exported_from_ui_components(self):
        from kira.ui.components import ModelCombo

        self.assertEqual(ModelCombo.__module__, "kira.ui.components.model_combo")

    def test_help_page_is_owned_by_ui_pages_package(self):
        from kira.ui.pages import HelpPage

        self.assertEqual(HelpPage.__module__, "kira.ui.pages.help_page")

    def test_dialogs_are_exported_without_importing_main_window(self):
        from kira.ui.dialogs import MemoryDialog, ModelPickerDialog

        self.assertEqual(MemoryDialog.__module__, "kira.ui.dialogs.memory")
        self.assertEqual(ModelPickerDialog.__module__, "kira.ui.dialogs.model_picker")


class ExtractedWorkerTests(unittest.TestCase):
    def test_background_workers_are_owned_by_ui_worker_module(self):
        from kira.ui.workers import (
            AttachWorker,
            BenchWorker,
            OllamaTaskWorker,
            ProviderTestWorker,
            SearchWorker,
            StreamWorker,
            TaskWorker,
            VisionAnalysisWorker,
        )

        worker_types = (
            AttachWorker,
            BenchWorker,
            OllamaTaskWorker,
            ProviderTestWorker,
            SearchWorker,
            StreamWorker,
            TaskWorker,
            VisionAnalysisWorker,
        )
        self.assertTrue(all(worker.__module__ == "kira.ui.workers" for worker in worker_types))


if __name__ == "__main__":
    unittest.main()
