"""Dead / no-longer-free models are switched off or removed instead of piling up in the Route list."""
import unittest

from tests import helpers
from kira import hybrid_ai, routes
from kira.hybrid_ai import ProviderError
from kira.app.detected_capabilities import DetectedCapabilities


def settings_with(*models, capabilities):
    s = helpers.fresh_settings()
    helpers.enable(s, "groq", "mistral")
    routes.ensure_routes(s, capabilities=capabilities)
    for rid in [r["id"] for r in routes.get_routes(s)]:
        routes.remove_route(s, rid, capabilities=capabilities)
    for provider, model in models:
        routes.add_route(s, provider, model)
    return s


class DisableRouteTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = DetectedCapabilities()

    def test_disables_and_remembers_the_reason(self):
        s = settings_with(("groq", "a"), ("groq", "b"), capabilities=self.capabilities)
        rid = routes.get_routes(s)[0]["id"]
        self.assertTrue(routes.disable_route(s, rid, "dead", capabilities=self.capabilities))
        self.assertFalse(routes.find_route(s, rid)["enabled"])
        self.assertEqual(routes.route_note(s, rid, capabilities=self.capabilities), "dead")
        routes.set_enabled(s, rid, True)
        self.assertEqual(routes.route_note(s, rid, capabilities=self.capabilities), "")          # the note disappears once the user re-enables it

    def test_never_disables_the_last_enabled_route(self):
        s = settings_with(("groq", "a"), capabilities=self.capabilities)
        rid = routes.get_routes(s)[0]["id"]
        self.assertFalse(routes.disable_route(s, rid, "dead", capabilities=self.capabilities))
        self.assertTrue(routes.find_route(s, rid)["enabled"])


class FreeModelTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = DetectedCapabilities()

    def test_only_an_explicit_paid_answer_disables(self):
        s = settings_with(("groq", "free-m"), ("groq", "paid-m"), ("groq", "unknown-m"), ("mistral", "other"), capabilities=self.capabilities)
        done = routes.disable_non_free_routes(s, "groq", {"free-m": True, "paid-m": False, "unknown-m": None}, capabilities=self.capabilities)
        enabled = {r["model"]: r["enabled"] for r in routes.get_routes(s)}
        self.assertEqual(len(done), 1)
        self.assertEqual(enabled, {"free-m": True, "paid-m": False, "unknown-m": True, "other": True})

    def test_switch_can_be_turned_off(self):
        s = settings_with(("groq", "free-m"), ("groq", "paid-m"), capabilities=self.capabilities)
        s["route_free_only"] = False
        self.assertEqual(routes.disable_non_free_routes(s, "groq", {"paid-m": False}, capabilities=self.capabilities), [])


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = DetectedCapabilities()

    def test_gone_models_are_removed(self):
        s = settings_with(("groq", "alive"), ("groq", "gone"), capabilities=self.capabilities)
        removed = routes.reconcile_provider_models(s, "groq", ["alive"], capabilities=self.capabilities)
        self.assertEqual(len(removed), 1)
        self.assertEqual([r["model"] for r in routes.get_routes(s)], ["alive"])

    def test_replacement_prefers_the_providers_recommended_model(self):
        s = settings_with(("groq", "gemini-2.5-flash"), ("mistral", "keep"), capabilities=self.capabilities)
        routes.reconcile_provider_models(
            s, "groq", ["aaa-old", "gemini-3.8-flash", "zzz"], prefer=("gemini-3.8-flash",),
            capabilities=self.capabilities)
        self.assertEqual([r["model"] for r in routes.get_routes(s) if r["provider"] == "groq"], ["gemini-3.8-flash"])

    def test_replacement_falls_back_to_a_free_model_then_alphabetical(self):
        s = settings_with(("groq", "old"), ("mistral", "keep"), capabilities=self.capabilities)
        routes.reconcile_provider_models(s, "groq", ["a-paid", "b-free"], free={"a-paid": False, "b-free": True}, capabilities=self.capabilities)
        self.assertEqual([r["model"] for r in routes.get_routes(s) if r["provider"] == "groq"], ["b-free"])

    def test_discovery_shape_list_of_dicts_keeps_valid_routes(self):
        """Regression: discovery returns [{'id': ...}, ...]; a valid route must not be treated as stale."""
        s = settings_with(("groq", "openai/gpt-oss-120b"), ("mistral", "keep"), capabilities=self.capabilities)
        catalog = [{"id": "openai/gpt-oss-120b", "free": None}, {"id": "llama-3.3", "free": True}]
        self.assertEqual(routes.reconcile_provider_models(s, "groq", catalog, capabilities=self.capabilities), [])
        self.assertEqual([r["model"] for r in routes.get_routes(s)], ["openai/gpt-oss-120b", "keep"])

    def test_catalog_helpers_accept_every_shape(self):
        as_list = [{"id": "a", "free": True}, {"id": "b"}, {"name": "no-id"}]
        as_dict = {"a": {"free": True}, "b": {}}
        for shape in (as_list, as_dict, ["a", "b"]):
            self.assertEqual(routes.catalog_ids(shape)[:2], ["a", "b"])
        self.assertEqual(routes.catalog_free(as_list), {"a": True, "b": None})
        self.assertEqual(routes.catalog_ids(None), [])

    def test_empty_catalog_changes_nothing(self):
        s = settings_with(("groq", "x"), ("groq", "y"), capabilities=self.capabilities)
        self.assertEqual(routes.reconcile_provider_models(s, "groq", [], capabilities=self.capabilities), [])
        self.assertEqual(len(routes.get_routes(s)), 2)


class RouterAutoDisableTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = DetectedCapabilities()

    def failure(self, router, route, kind):
        router._mark_failure(route, ProviderError("groq", "boom", False, 404 if kind == "model" else 500, kind))

    def test_two_model_errors_in_a_row_switch_the_route_off(self):
        s = settings_with(("groq", "dead"), ("mistral", "ok"), capabilities=self.capabilities)
        router = hybrid_ai.HybridRouter(s, detected_capabilities=self.capabilities)
        route = routes.get_routes(s)[0]
        self.failure(router, route, "model")
        self.assertTrue(routes.find_route(s, route["id"])["enabled"])
        self.failure(router, route, "model")
        self.assertFalse(routes.find_route(s, route["id"])["enabled"])
        self.assertIn("boom", routes.route_note(s, route["id"], capabilities=self.capabilities))

    def test_a_success_or_other_error_in_between_resets_the_count(self):
        s = settings_with(("groq", "flaky"), ("mistral", "ok"), capabilities=self.capabilities)
        router = hybrid_ai.HybridRouter(s)
        route = routes.get_routes(s)[0]
        self.failure(router, route, "model")
        self.failure(router, route, "server")
        self.failure(router, route, "model")
        self.assertTrue(routes.find_route(s, route["id"])["enabled"])


if __name__ == "__main__":
    unittest.main()


class GoogleTimeoutTests(unittest.TestCase):
    """The connection test must use the same Gemini timeout as real chat (it used to cut off at the 18 s default)."""

    def make(self, timeout=None):
        s = helpers.fresh_settings()
        pid = routes.add_provider(s, "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta/openai",
                                  api_key="k-" + "x" * 20)
        route = routes.add_route(s, pid, "gemini-3.8-flash", timeout=timeout)
        return s, route, s["providers"][pid]

    def test_default_google_route_gets_the_cloud_maximum(self):
        _, route, cfg = self.make()
        self.assertEqual(routes.effective_timeout(route, cfg), routes.CLOUD_TIMEOUT[1])

    def test_explicit_longer_value_is_kept_and_other_providers_untouched(self):
        _, route, cfg = self.make(timeout=40)
        self.assertEqual(routes.effective_timeout(route, cfg), 40)
        other = {"provider": "groq", "timeout": 18}
        self.assertEqual(routes.effective_timeout(other, {}), 18)

    def test_route_test_passes_the_extended_timeout_to_the_probe(self):
        from unittest import mock
        s, route, _ = self.make()
        router = hybrid_ai.HybridRouter(s)
        with mock.patch.object(hybrid_ai, "probe_provider", return_value=(True, "ok")) as probe:
            router.test_route(route["id"])
        self.assertEqual(probe.call_args.args[1]["timeout"], routes.CLOUD_TIMEOUT[1])
