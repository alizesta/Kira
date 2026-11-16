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


class ExtractedUiComponentTests(unittest.TestCase):
    def test_model_combo_is_exported_from_ui_components(self):
        from kira.ui.components import ModelCombo

        self.assertEqual(ModelCombo.__module__, "kira.ui.components.model_combo")

    def test_dialogs_are_exported_without_importing_main_window(self):
        from kira.ui.dialogs import MemoryDialog, ModelPickerDialog

        self.assertEqual(MemoryDialog.__module__, "kira.ui.dialogs.memory")
        self.assertEqual(ModelPickerDialog.__module__, "kira.ui.dialogs.model_picker")


if __name__ == "__main__":
    unittest.main()
