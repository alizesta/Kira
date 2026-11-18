"""Provider registry and adapter contract tests."""
from __future__ import annotations

import unittest

from kira.core.interfaces import ChatProvider
from kira.hybrid_ai import (
    GroqProvider,
    PROVIDER_REGISTRY,
    provider_class,
)
from kira.infrastructure.providers import ProviderRegistry


class ProviderRegistryTests(unittest.TestCase):
    def test_registry_register_replace_resolve_and_unregister(self):
        registry = ProviderRegistry()
        original = lambda: "first"
        replacement = lambda: "second"
        registry.register("Example", original)
        self.assertIs(registry.resolve("example"), original)
        with self.assertRaises(ValueError):
            registry.register("example", replacement)
        registry.register("EXAMPLE", replacement, replace=True)
        self.assertIs(registry.resolve("example"), replacement)
        self.assertTrue(registry.unregister("example"))
        self.assertIsNone(registry.resolve("example"))
        self.assertFalse(registry.unregister("example"))

    def test_router_resolves_replaceable_registered_adapter(self):
        original = provider_class("groq")

        class Replacement:
            pass

        try:
            PROVIDER_REGISTRY.register("groq", Replacement, replace=True)
            self.assertIs(provider_class("groq"), Replacement)
        finally:
            PROVIDER_REGISTRY.register("groq", original, replace=True)

    def test_builtin_adapter_satisfies_chat_provider_contract(self):
        provider = GroqProvider({"enabled": False}, name="groq")
        self.assertIsInstance(provider, ChatProvider)
        self.assertTrue(callable(provider.chat))
        self.assertTrue(callable(provider.stream))
        self.assertTrue(callable(provider.abort))


if __name__ == "__main__":
    unittest.main()
