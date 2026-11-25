"""Regression coverage for refreshed model catalogs and configured failover priority."""
import time
import unittest

from kira import routes
from kira.hybrid_ai import CloudflareProvider, GroqProvider, HybridRouter, ProviderError


class _Response:
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.headers = {}
        self._message = message

    def json(self):
        return {"errors": [{"message": self._message}]}

    @property
    def text(self):
        return self._message


class ModelCatalogReconciliationTests(unittest.TestCase):
    def _settings(self):
        return {
            "providers": {"groq": {"enabled": True, "api_key": "test-key"}},
            "routes": [
                {"id": "groq-main", "provider": "groq", "model": "old-model", "enabled": True},
                {"id": "groq-extra", "provider": "groq", "model": "removed-model", "enabled": True},
            ],
            "manual_route_id": "groq-extra",
            "default_route_id": "groq-main",
        }

    def test_refresh_removes_stale_routes_when_a_current_route_remains(self):
        settings = self._settings()
        removed = routes.reconcile_provider_models(settings, "groq", ["old-model", "new-model"])
        self.assertEqual(removed, ["groq-extra"])
        self.assertEqual([r["model"] for r in routes.get_routes(settings) if r["provider"] == "groq"], ["old-model"])
        self.assertEqual(settings["manual_route_id"], "")

    def test_refresh_retargets_one_route_when_every_old_model_was_removed(self):
        settings = self._settings()
        removed = routes.reconcile_provider_models(settings, "groq", ["replacement-model"])
        active = [r for r in routes.get_routes(settings) if r["provider"] == "groq"]
        self.assertEqual(removed, ["groq-extra"])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["model"], "replacement-model")
        self.assertEqual(active[0]["id"], "groq-main")

    def test_empty_discovery_never_deletes_existing_routes(self):
        settings = self._settings()
        before = routes.snapshot(settings)
        self.assertEqual(routes.reconcile_provider_models(settings, "groq", []), [])
        self.assertEqual(routes.snapshot(settings), before)


class RoutePriorityTests(unittest.TestCase):
    def test_measured_latency_does_not_reorder_configured_route_priority(self):
        settings = {
            "providers": {
                "groq": {"enabled": True, "api_key": "key"},
                "mistral": {"enabled": True, "api_key": "key"},
                "openrouter": {"enabled": True, "api_key": "key"},
            },
            "routes": [
                {"id": "slow", "provider": "groq", "model": "slow-model", "enabled": True},
                {"id": "limited", "provider": "mistral", "model": "limited-model", "enabled": True},
                {"id": "fast", "provider": "openrouter", "model": "fast-model", "enabled": True},
            ],
            "failover_enabled": True,
        }
        router = HybridRouter(settings)
        router.states["slow"] = {"latency_ms": 520, "last_kind": None}
        router.states["limited"] = {"latency_ms": 15, "last_kind": "rate"}
        router.states["fast"] = {"latency_ms": 90, "last_kind": None}
        router.cooldowns["limited"] = time.monotonic() + 120
        self.assertEqual([r["id"] for r in router._candidates()], ["slow", "limited", "fast"])

    def test_known_and_unknown_latency_both_preserve_configured_order(self):
        settings = {
            "providers": {
                "groq": {"enabled": True, "api_key": "key"},
                "mistral": {"enabled": True, "api_key": "key"},
            },
            "routes": [
                {"id": "unknown", "provider": "groq", "model": "unknown-model", "enabled": True},
                {"id": "known", "provider": "mistral", "model": "known-model", "enabled": True},
            ],
            "failover_enabled": True,
        }
        router = HybridRouter(settings)
        router.states["known"] = {"latency_ms": 140, "last_kind": None}
        self.assertEqual([r["id"] for r in router._candidates()], ["unknown", "known"])


class ProviderErrorClassificationTests(unittest.TestCase):
    def test_cloudflare_plan_gate_is_not_misreported_as_invalid_token(self):
        provider = CloudflareProvider({"model": "@cf/deepseek/model", "api_key": "secret", "account_id": "account"})
        with self.assertRaises(ProviderError) as caught:
            provider._check_status(_Response(403, "Model is not available on the Workers Free plan"))
        self.assertEqual(caught.exception.kind, "model")
        self.assertEqual(caught.exception.status_code, 403)

    def test_groq_network_block_403_is_not_misreported_as_bad_credentials(self):
        provider = GroqProvider({"model": "openai/gpt-oss-120b", "api_key": "secret"})
        with self.assertRaises(ProviderError) as caught:
            provider._check_status(_Response(403, "Access denied. Please check your network settings."))
        self.assertEqual(caught.exception.kind, "network")


if __name__ == "__main__":
    unittest.main()
