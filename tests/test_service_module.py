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

    def test_module_enable_disable_recreates_and_releases_service(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        created = []

        class Service:
            def __init__(self):
                self.started = False
                self.stopped = False
                self.closed = False
                created.append(self)

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

            def close(self):
                self.closed = True

        manager.register("optional", lambda: ServiceModule("optional_service", Service))
        manager.start("optional")
        first = container.resolve("optional_service")
        self.assertTrue(first.started)

        manager.disable("optional")
        self.assertTrue(first.stopped)
        self.assertTrue(first.closed)
        with self.assertRaises(KeyError):
            container.resolve("optional_service")

        manager.enable("optional")
        second = container.resolve("optional_service")
        self.assertIsNot(first, second)
        self.assertTrue(second.started)
        manager.shutdown()
        self.assertTrue(second.stopped)
        self.assertTrue(second.closed)

    def test_shutdown_unregisters_service_even_when_cleanup_raises(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())

        class BrokenCleanupService:
            def stop(self):
                pass

            def close(self):
                raise RuntimeError("cleanup failed")

        manager.register(
            "fragile",
            lambda: ServiceModule("fragile_service", BrokenCleanupService),
        )
        manager.start("fragile")
        self.assertIsInstance(container.resolve("fragile_service"), BrokenCleanupService)

        errors = manager.shutdown()

        self.assertIn("fragile", errors)
        self.assertIn("dispose: RuntimeError: cleanup failed", errors["fragile"])
        self.assertEqual(manager.state("fragile"), ModuleState.DISPOSED)
        with self.assertRaises(KeyError):
            container.resolve("fragile_service")

    def test_stopped_service_restarts_without_recreating_its_instance(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        events = []

        class RestartableService:
            def start(self):
                events.append("start")

            def stop(self):
                events.append("stop")

            def close(self):
                events.append("close")

        manager.register(
            "restartable",
            lambda: ServiceModule("restartable_service", RestartableService),
        )
        manager.start("restartable")
        first = container.resolve("restartable_service")
        manager.stop("restartable")
        manager.start("restartable")

        self.assertIs(container.resolve("restartable_service"), first)
        self.assertEqual(events, ["start", "stop", "start"])
        manager.shutdown()
        self.assertEqual(events, ["start", "stop", "start", "stop", "close"])

    def test_failed_start_stops_and_disposes_partial_service(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        events = []

        class PartialService:
            def start(self):
                events.append("start")
                raise RuntimeError("partial start")

            def stop(self):
                events.append("stop")

            def close(self):
                events.append("close")

        manager.register(
            "partial",
            lambda: ServiceModule("partial_service", PartialService),
        )
        states = manager.start_all()

        self.assertEqual(states["partial"], ModuleState.FAILED)
        self.assertEqual(events, ["start", "stop", "close"])
        with self.assertRaises(KeyError):
            container.resolve("partial_service")
        self.assertEqual(manager.shutdown(), {})

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
