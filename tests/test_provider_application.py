"""Qt-free tests for provider application policy."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from kira.app.provider_application import ProviderApplicationService
from kira import routes as route_model


class ProviderApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ProviderApplicationService()
        self.settings = {"providers": {"ollama": {"enabled": True}}, "routes": []}

    def test_add_provider_and_first_route_are_created_together(self):
        provider_id = self.service.add_provider(
            self.settings, "Local Gateway", "http://127.0.0.1:1234/v1",
            local=True, first_model="test-model",
        )
        self.assertIn(provider_id, self.settings["providers"])
        route = next(r for r in self.settings["routes"] if r["provider"] == provider_id)
        self.assertEqual(route["model"], "test-model")

    def test_add_provider_rolls_back_when_initial_route_is_invalid(self):
        before = deepcopy(self.settings)
        with patch("kira.app.provider_application.route_model.add_route", side_effect=ValueError("route rejected")):
            with self.assertRaisesRegex(ValueError, "route rejected"):
                self.service.add_provider(
                    self.settings, "Local Gateway", "http://127.0.0.1:1234/v1",
                    local=True, first_model="test-model",
                )
        self.assertEqual(self.settings, before)

    def test_ollama_url_validation_is_atomic(self):
        self.service.update_ollama_url(self.settings, "http://localhost:11434/")
        self.assertEqual(self.settings["ollama_url"], "http://localhost:11434")
        self.assertEqual(self.settings["providers"]["ollama"]["base_url"], "http://localhost:11434")
        before = dict(self.settings)
        with self.assertRaises(ValueError):
            self.service.update_ollama_url(self.settings, "not a url")
        self.assertEqual(self.settings, before)

    def test_remove_provider_clears_its_detected_registry_record(self):
        provider_id = self.service.add_provider(
            self.settings, "Custom", "https://example.test/v1", first_model="model-a"
        )
        self.service.registry()[provider_id] = {"status": "valid"}
        removed_routes = route_model.get_routes(self.settings)
        route_id = next(route["id"] for route in removed_routes if route["provider"] == provider_id)
        self.service.detected_capabilities.mapping_set("route_notes", route_id, "temporary provider error")
        removed = self.service.remove_provider(self.settings, provider_id)
        self.assertTrue(removed)
        self.assertNotIn(provider_id, self.settings["providers"])
        self.assertNotIn(provider_id, self.service.registry())
        self.assertIsNone(self.service.detected_capabilities.mapping_get("route_notes", route_id))

    def test_explicit_model_enable_clears_automatic_disable_note(self):
        provider_id = self.service.add_provider(
            self.settings, "Custom", "https://example.test/v1", first_model="model-a"
        )
        route = next(route for route in route_model.get_routes(self.settings) if route["provider"] == provider_id)
        route_model.update_route(self.settings, route["id"], enabled=False)
        self.service.detected_capabilities.mapping_set("route_notes", route["id"], "previous automatic failure")

        self.service.set_model_enabled(self.settings, provider_id, "model-a", True)

        self.assertTrue(route_model.find_route(self.settings, route["id"])["enabled"])
        self.assertIsNone(
            self.service.detected_capabilities.mapping_get("route_notes", route["id"])
        )

    def test_delete_api_clears_detected_route_notes(self):
        provider_id = "groq"
        routes = [route for route in route_model.get_routes(self.settings) if route["provider"] == provider_id]
        if not routes:
            route_model.add_route(self.settings, provider_id, "openai/gpt-oss-120b", enabled=True)
            routes = [route for route in route_model.get_routes(self.settings) if route["provider"] == provider_id]
        route_id = routes[0]["id"]
        self.service.detected_capabilities.mapping_set("route_notes", route_id, "previous automatic failure")
        self.service.delete_api(self.settings, provider_id)
        self.assertIsNone(
            self.service.detected_capabilities.mapping_get("route_notes", route_id)
        )

    def test_builtin_provider_cannot_be_removed(self):
        with self.assertRaises(ValueError):
            self.service.remove_provider(self.settings, "ollama")

    def test_create_ollama_client_from_dialog_values_is_a_provider_service_operation(self):
        service = ProviderApplicationService()
        client = service.create_ollama_client_from_values(
            "http://localhost:11434",
            "qwen2.5:3b",
            num_ctx=4096,
            keep_alive="5m",
            num_predict=512,
        )
        self.assertEqual(client.base_url, "http://localhost:11434")
        self.assertEqual(client.model, "qwen2.5:3b")
        self.assertEqual(client.num_ctx, 4096)
        self.assertEqual(client.keep_alive, "5m")
        self.assertEqual(client.num_predict, 512)

    def test_router_rebuild_preserves_shared_health_state_and_resets_cooldowns(self):
        class Router:
            def __init__(self, settings):
                self.settings = settings
                self.states = {}
                self.cooldowns = {}

        class Session:
            def __init__(self, client):
                self.client = client

        previous = Router(self.settings)
        previous.states = {"route-a": {"health": "healthy"}}
        previous.cooldowns = {"route-a": 30.0}
        first, second = Session(previous), Session(previous)
        created = []
        service = ProviderApplicationService(
            router_factory=lambda settings: created.append(Router(settings)) or created[-1]
        )

        routers = service.rebuild_session_routers(
            self.settings, (first, second), previous_router=previous
        )

        self.assertEqual(len(routers), 2)
        self.assertIs(first.client, routers[0])
        self.assertIs(second.client, routers[1])
        self.assertIsNot(first.client, previous)
        self.assertIs(first.client.states, previous.states)
        self.assertIs(first.client.cooldowns, second.client.cooldowns)
        self.assertEqual(first.client.cooldowns, {})

    def test_router_factory_failure_does_not_partially_replace_sessions(self):
        class Router:
            def __init__(self, name):
                self.name = name
                self.states = {}
                self.cooldowns = {}

        class Session:
            def __init__(self, client):
                self.client = client

        old_a, old_b = Router("old-a"), Router("old-b")
        first, second = Session(old_a), Session(old_b)
        calls = []

        def factory(settings):
            calls.append(settings)
            if len(calls) == 2:
                raise RuntimeError("router creation failed")
            return Router("new")

        service = ProviderApplicationService(router_factory=factory)
        with self.assertRaisesRegex(RuntimeError, "router creation failed"):
            service.rebuild_session_routers(self.settings, (first, second), previous_router=old_a)

        self.assertIs(first.client, old_a)
        self.assertIs(second.client, old_b)

    def test_isolated_router_copies_health_without_sharing_cancellation_state(self):
        class Router:
            def __init__(self, settings):
                self.settings = settings
                self.states = {}
                self.cooldowns = {}
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        previous = Router(self.settings)
        previous.states = {"route-a": {"health": "healthy"}}
        previous.cooldowns = {"route-a": 12.0}
        created = []
        service = ProviderApplicationService(
            router_factory=lambda settings: created.append(Router(settings)) or created[-1]
        )

        isolated = service.create_isolated_router(self.settings, previous_router=previous)

        self.assertIsNot(isolated, previous)
        self.assertEqual(isolated.states, previous.states)
        self.assertIsNot(isolated.states, previous.states)
        self.assertIsNot(isolated.states["route-a"], previous.states["route-a"])
        self.assertEqual(isolated.cooldowns, previous.cooldowns)
        self.assertIsNot(isolated.cooldowns, previous.cooldowns)
        isolated.cancel()
        self.assertTrue(isolated.cancelled)
        self.assertFalse(previous.cancelled)

    def test_isolated_router_rejects_a_factory_that_reuses_the_chat_router(self):
        router = object()
        service = ProviderApplicationService(router_factory=lambda _settings: router)
        with self.assertRaisesRegex(RuntimeError, "previous router"):
            service.create_isolated_router(self.settings, previous_router=router)

    def test_router_factory_receives_current_settings(self):
        seen = []
        marker = object()
        service = ProviderApplicationService(router_factory=lambda settings: seen.append(settings) or marker)
        self.assertIs(service.create_router(self.settings), marker)
        self.assertEqual(seen, [self.settings])

    def test_detected_capabilities_are_service_scoped_not_persisted_settings(self):
        from kira.app.detected_capabilities import DetectedCapabilities

        settings = {
            "providers": {
                "ollama": {"enabled": False},
                "groq": {"enabled": True, "api_key": "gsk_" + "x" * 40, "model": "model-a"},
            },
            "routes": [
                {"id": "groq", "provider": "groq", "model": "model-a", "enabled": True},
            ],
        }
        first, second = ProviderApplicationService(), ProviderApplicationService()
        first.ensure_registry(settings)
        first.apply_models(settings, "groq", [{"id": "model-a", "context": 8192}])
        first.set_ollama_models(["local-model"])

        first_entry = first.registry()["groq"]
        second_rows = second.api_rows(settings)
        second_entry = second.registry()["groq"]

        self.assertEqual(first_entry["models"]["model-a"]["status"], "available")
        self.assertEqual(second_entry["models"]["model-a"]["status"], "unknown")
        self.assertEqual(second_rows[0]["status"], "not validated yet")
        self.assertEqual(first.ollama_models, ("local-model",))
        self.assertEqual(second.ollama_models, ())
        self.assertNotIn("api_registry", settings)
        self.assertNotIn("ollama_models", settings)
        self.assertIsInstance(first.detected_capabilities, DetectedCapabilities)
        self.assertIsNot(first.detected_capabilities, second.detected_capabilities)

    def test_runtime_and_detected_capabilities_have_independent_lifecycles(self):
        from kira.app.runtime_state import RuntimeState
        from kira.app.detected_capabilities import DetectedCapabilities

        runtime = RuntimeState({"worker", "closing"})
        capabilities = DetectedCapabilities()
        worker = object()
        runtime.set("worker", worker)
        runtime.set("closing", False)
        capabilities.set("api_registry", {"groq": {"status": "valid"}})
        capabilities.set("ollama_models", ("qwen-local",))

        self.assertIs(runtime.get("worker"), worker)
        self.assertIn("worker", runtime.snapshot())
        self.assertNotIn("api_registry", runtime.snapshot())
        self.assertNotIn("worker", capabilities.snapshot())
        self.assertEqual(capabilities.get("ollama_models"), ("qwen-local",))
        with self.assertRaises(KeyError):
            runtime.set("api_registry", {})
        with self.assertRaises(KeyError):
            capabilities.set("settings", {})
        runtime.clear("worker")
        capabilities.clear()
        self.assertNotIn("worker", runtime.snapshot())
        self.assertEqual(capabilities.snapshot(), {})

    def test_model_test_results_live_in_detected_capabilities(self):
        from kira import model_catalog
        first = ProviderApplicationService()
        second = ProviderApplicationService()
        model_catalog.record_test(
            self.settings, "groq", "model-a", True, 12, "ok",
            capabilities=first.detected_capabilities,
        )
        self.assertTrue(model_catalog.test_result(
            self.settings, "groq", "model-a", capabilities=first.detected_capabilities
        )["ok"])
        self.assertIsNone(model_catalog.test_result(
            self.settings, "groq", "model-a", capabilities=second.detected_capabilities
        ))
        self.assertNotIn("model_tests", self.settings)

    def test_api_model_operations_delegate_to_existing_registry_owner(self):
        detection = object()
        with patch("kira.app.provider_application.api_manager.apply_models", return_value={"new": [], "gone": []}) as apply:
            self.service.apply_models(self.settings, "groq", [], {})
        apply.assert_called_once_with(self.settings, "groq", [], {}, capabilities=self.service.detected_capabilities)
        with patch("kira.app.provider_application.api_manager.apply_failure") as fail:
            self.service.apply_failure(self.settings, "groq", detection)
        fail.assert_called_once_with(self.settings, "groq", detection, capabilities=self.service.detected_capabilities)


if __name__ == "__main__":
    unittest.main()
