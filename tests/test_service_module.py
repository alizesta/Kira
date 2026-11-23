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


    def test_lazy_service_is_realized_only_when_first_used(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        events = []

        class LazyService:
            def start(self):
                events.append("start")

            def run(self):
                events.append("run")
                return "ready"

            def stop(self):
                events.append("stop")

            def close(self):
                events.append("close")

        def factory():
            events.append("create")
            return LazyService()

        manager.register(
            "lazy",
            lambda: ServiceModule("lazy_service", factory, lazy=True),
        )
        manager.start("lazy")
        proxy = container.resolve("lazy_service")
        self.assertEqual(events, [])

        self.assertEqual(proxy.run(), "ready")
        self.assertEqual(events, ["create", "start", "run"])

        self.assertEqual(manager.shutdown(), {})
        self.assertEqual(events, ["create", "start", "run", "stop", "close"])

    def test_lazy_service_failed_start_releases_partial_instance_and_retries_fresh(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        events = []
        created = []

        class LazyService:
            def __init__(self, should_fail):
                self.should_fail = should_fail

            def start(self):
                events.append(("start", self.should_fail))
                if self.should_fail:
                    raise RuntimeError("partial lazy start")

            def run(self):
                return "ready"

            def stop(self):
                events.append(("stop", self.should_fail))

            def close(self):
                events.append(("close", self.should_fail))

        def factory():
            should_fail = not created
            service = LazyService(should_fail)
            created.append(service)
            return service

        manager.register(
            "lazy",
            lambda: ServiceModule("lazy_service", factory, lazy=True),
        )
        manager.start("lazy")
        proxy = container.resolve("lazy_service")

        with self.assertRaisesRegex(RuntimeError, "partial lazy start"):
            proxy.run()

        self.assertEqual(
            events,
            [("start", True), ("stop", True), ("close", True)],
        )
        self.assertEqual(proxy.run(), "ready")
        self.assertEqual(len(created), 2)
        self.assertIsNot(created[0], created[1])
        manager.shutdown()
        self.assertEqual(events[-2:], [("stop", False), ("close", False)])

    def test_lazy_service_disposal_attempts_close_after_stop_failure(self):
        container = DependencyContainer()
        manager = ModuleManager(container, EventBus())
        created = []
        closed = []

        class BrokenStopService:
            def start(self):
                pass

            def run(self):
                return "active"

            def stop(self):
                raise RuntimeError("stop failed")

            def close(self):
                closed.append(True)

        def factory():
            service = BrokenStopService()
            created.append(service)
            return service

        manager.register(
            "lazy",
            lambda: ServiceModule("lazy_service", factory, lazy=True),
        )
        manager.start("lazy")
        proxy = container.resolve("lazy_service")
        self.assertEqual(proxy.run(), "active")

        errors = manager.shutdown()
        self.assertIn("lazy", errors)
        self.assertEqual(closed, [True])
        with self.assertRaisesRegex(RuntimeError, "disposed"):
            proxy.run()
        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
