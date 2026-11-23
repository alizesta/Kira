from __future__ import annotations

import unittest

from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.service_module import ServiceModule


class _Service:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.disposed = 0

    @property
    def label(self):
        return "lazy"

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def dispose(self):
        self.disposed += 1

    def read(self):
        return "ready"


class LazyServiceModuleTests(unittest.TestCase):
    def test_service_is_not_constructed_or_started_until_first_method_call(self):
        created = []
        container = DependencyContainer()
        module = ServiceModule("lazy_service", lambda: created.append(_Service()) or created[-1], lazy=True)
        module.register(container, EventBus())
        module.start()

        proxy = container.resolve("lazy_service")
        self.assertEqual(created, [])
        self.assertEqual(proxy.read(), "ready")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].started, 1)

    def test_method_lookup_does_not_realize_the_service_until_invoked(self):
        created = []
        container = DependencyContainer()
        module = ServiceModule("lazy_service", lambda: created.append(_Service()) or created[-1], lazy=True)
        module.register(container, EventBus())
        module.start()
        proxy = container.resolve("lazy_service")

        read = proxy.read
        self.assertEqual(created, [])
        self.assertEqual(read(), "ready")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].started, 1)

    def test_lazy_service_data_attributes_keep_the_wrapped_contract(self):
        created = []
        container = DependencyContainer()
        module = ServiceModule("lazy_service", lambda: created.append(_Service()) or created[-1], lazy=True)
        module.register(container, EventBus())
        module.start()
        proxy = container.resolve("lazy_service")

        self.assertEqual(created, [])
        self.assertEqual(proxy.value("label"), "lazy")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].started, 1)

    def test_lazy_service_lifecycle_is_forwarded_after_realization(self):
        created = []
        container = DependencyContainer()
        module = ServiceModule("lazy_service", lambda: created.append(_Service()) or created[-1], lazy=True)
        module.register(container, EventBus())
        module.start()
        proxy = container.resolve("lazy_service")

        module.stop()
        self.assertEqual(created, [])
        self.assertEqual(proxy.read(), "ready")
        self.assertEqual(created[0].started, 1)
        module.stop()
        self.assertEqual(created[0].stopped, 1)
        module.dispose()
        self.assertEqual(created[0].disposed, 1)


if __name__ == "__main__":
    unittest.main()
