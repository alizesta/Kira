"""Qt-free tests for provider application policy."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from kira.app.provider_application import ProviderApplicationService


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

    def test_remove_provider_also_removes_its_api_registry_record(self):
        provider_id = self.service.add_provider(
            self.settings, "Custom", "https://example.test/v1", first_model="model-a"
        )
        self.settings["api_registry"] = {provider_id: {"status": "valid"}}
        removed = self.service.remove_provider(self.settings, provider_id)
        self.assertTrue(removed)
        self.assertNotIn(provider_id, self.settings["providers"])
        self.assertNotIn(provider_id, self.settings["api_registry"])

    def test_builtin_provider_cannot_be_removed(self):
        with self.assertRaises(ValueError):
            self.service.remove_provider(self.settings, "ollama")

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

    def test_router_factory_receives_current_settings(self):
        seen = []
        marker = object()
        service = ProviderApplicationService(router_factory=lambda settings: seen.append(settings) or marker)
        self.assertIs(service.create_router(self.settings), marker)
        self.assertEqual(seen, [self.settings])

    def test_api_model_operations_delegate_to_existing_registry_owner(self):
        detection = object()
        with patch("kira.app.provider_application.api_manager.apply_models", return_value={"new": [], "gone": []}) as apply:
            self.service.apply_models(self.settings, "groq", [], {})
        apply.assert_called_once_with(self.settings, "groq", [], {})
        with patch("kira.app.provider_application.api_manager.apply_failure") as fail:
            self.service.apply_failure(self.settings, "groq", detection)
        fail.assert_called_once_with(self.settings, "groq", detection)


if __name__ == "__main__":
    unittest.main()
