"""Contract tests for explicit feature-controller ownership and dispatch."""
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

    def test_missing_feature_attribute_raises_attribute_error(self):
        with self.assertRaises(AttributeError):
            self.registry.resolve("not_a_feature_method")


if __name__ == "__main__":
    unittest.main()
