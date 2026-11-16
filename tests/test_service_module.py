"""Tests for lifecycle-managed application service registrations."""
from __future__ import annotations

import unittest

from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.module_manager import ModuleManager, ModuleState
from kira.modules import ServiceModule


class ServiceModuleTests(unittest.TestCase):
    def test_service_is_registered_on_start_and_removed_on_dispose(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        service = object()
        manager.register("sample", lambda: ServiceModule("sample_service", lambda: service))

        states = manager.start_all()
        self.assertEqual(states["sample"], ModuleState.STARTED)
        self.assertIs(container.resolve("sample_service"), service)

        manager.shutdown()
        self.assertEqual(manager.state("sample"), ModuleState.DISPOSED)
        with self.assertRaises(KeyError):
            container.resolve("sample_service")

    def test_unrelated_service_modules_start_independently(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        manager.register("first", lambda: ServiceModule("first_service", object))
        manager.register("second", lambda: ServiceModule("second_service", object))

        states = manager.start_all()
        self.assertEqual(states, {
            "first": ModuleState.STARTED,
            "second": ModuleState.STARTED,
        })
        self.assertIsNotNone(container.resolve("first_service"))
        self.assertIsNotNone(container.resolve("second_service"))
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
