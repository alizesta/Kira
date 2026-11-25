import copy
import unittest

from tests import helpers  # noqa: F401  (redirects Kira's data folder to a temp dir)
from kira import config
from kira.route_policy import RoutePolicyEngine, normalize_network_policy
from kira.settings_schema import DEFAULTS, SETTINGS_SCHEMA_VERSION

CLOUD_SURFACE = ("groq", "cloudflare", "mistral", "openrouter", "google")
DEFAULT_SURFACE_ALLOWLIST = ["ollama", *CLOUD_SURFACE]


def _select(settings, routes, role="surface"):
    return RoutePolicyEngine().select(
        routes,
        settings,
        role=role,
        provider_cfg=lambda route: {},
        provider_kind=lambda provider, cfg: "local" if provider == "ollama" else "cloud",
        is_google=lambda provider, cfg: provider == "google",
        supports_vision=lambda *args: True,
    )


class NetworkPolicyDefaultTests(unittest.TestCase):
    def test_schema_version_is_at_least_8(self):
        self.assertGreaterEqual(SETTINGS_SCHEMA_VERSION, 8)

    def test_defaults_permit_cloud_for_normal_chat(self):
        self.assertEqual(DEFAULTS["network_policy"], "cloud_permitted")
        surface = DEFAULTS["role_provider_allowlist"]["surface"]
        for provider in ("ollama", *CLOUD_SURFACE):
            self.assertIn(provider, surface)
        self.assertEqual(DEFAULTS["role_provider_allowlist"]["deep"], ["google"])
        self.assertEqual(DEFAULTS["role_provider_allowlist"]["reflection"], ["google"])
        self.assertEqual(DEFAULTS["role_provider_allowlist"]["memory"], ["ollama"])

    def test_unknown_policy_values_still_fail_closed(self):
        for value in (None, "", "garbage", 5, "LOCAL"):
            self.assertEqual(normalize_network_policy(value), "local_only")
        self.assertEqual(normalize_network_policy(" Cloud_Permitted "), "cloud_permitted")

    def test_v7_untouched_default_state_migrates_to_cloud_permitted(self):
        source = {
            "settings_version": 7,
            "network_policy": "local_only",
            "role_provider_allowlist": {
                "surface": ["ollama"], "deep": ["google"],
                "reflection": ["google"], "memory": ["ollama"],
            },
            "user_extension": {"keep": True},
        }
        warnings = []
        migrated = config._migrate_settings(source, warnings=warnings)

        self.assertEqual(migrated["settings_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(migrated["network_policy"], "cloud_permitted")
        self.assertEqual(migrated["role_provider_allowlist"]["surface"], DEFAULT_SURFACE_ALLOWLIST)
        self.assertEqual(migrated["role_provider_allowlist"]["deep"], ["google"])
        self.assertEqual(migrated["role_provider_allowlist"]["memory"], ["ollama"])
        self.assertEqual(migrated["user_extension"], {"keep": True})
        self.assertTrue(warnings)
        # The caller's data is never mutated and a second pass changes nothing.
        self.assertEqual(source["network_policy"], "local_only")
        self.assertEqual(source["role_provider_allowlist"]["surface"], ["ollama"])
        self.assertEqual(config._migrate_settings(migrated), migrated)

    def test_customized_surface_allowlist_keeps_local_only(self):
        source = {
            "settings_version": 7,
            "network_policy": "local_only",
            "role_provider_allowlist": {"surface": ["ollama", "mistral"]},
        }
        migrated = config._migrate_settings(source)
        self.assertEqual(migrated["network_policy"], "local_only")
        self.assertEqual(migrated["role_provider_allowlist"]["surface"], ["ollama", "mistral"])

    def test_explicit_cloud_permitted_is_not_rewritten(self):
        source = {
            "settings_version": 7,
            "network_policy": "cloud_permitted",
            "role_provider_allowlist": {"surface": ["ollama"]},
        }
        migrated = config._migrate_settings(source)
        self.assertEqual(migrated["network_policy"], "cloud_permitted")
        self.assertEqual(migrated["role_provider_allowlist"]["surface"], ["ollama"])

    def test_missing_policy_is_left_for_the_new_default(self):
        migrated = config._migrate_settings({"settings_version": 7, "assistant_name": "Kira"})
        self.assertNotIn("network_policy", migrated)

    def test_default_settings_route_normal_chat_to_an_enabled_cloud_provider(self):
        settings = copy.deepcopy(DEFAULTS)
        routes = [{"id": "groq", "provider": "groq", "model": "openai/gpt-oss-120b"}]
        ordered, decisions = _select(settings, routes)
        self.assertEqual([route["id"] for route in ordered], ["groq"])
        self.assertTrue(all(decision.allowed for decision in decisions if decision.route_id == "groq"))

    def test_choosing_local_only_still_blocks_cloud_routes(self):
        settings = copy.deepcopy(DEFAULTS)
        settings["network_policy"] = "local_only"
        routes = [{"id": "groq", "provider": "groq", "model": "openai/gpt-oss-120b"}]
        ordered, decisions = _select(settings, routes)
        self.assertEqual(ordered, [])
        self.assertEqual(
            [(d.route_id, d.reason) for d in decisions if not d.allowed],
            [("groq", "blocked_by_local_only")],
        )


if __name__ == "__main__":
    unittest.main()
