"""Tab rules, archiving and saved quick-test results of the "مدل‌ها" box (Qt-free)."""
import unittest

from tests import helpers
from kira import api_manager, model_catalog as mc, routes
from kira.app.detected_capabilities import DetectedCapabilities


CAPABILITIES = DetectedCapabilities()


def catalog_rows(settings):
    return mc.model_rows(settings, capabilities=CAPABILITIES)


def build():
    CAPABILITIES.clear()
    s = helpers.fresh_settings()
    helpers.enable(s, "groq", "mistral")
    routes.ensure_routes(s)
    for rid in [r["id"] for r in routes.get_routes(s)]:
        routes.remove_route(s, rid)
    api_manager.ensure_registry(s, CAPABILITIES)
    api_manager.apply_models(s, "groq", [
        {"id": "free-a", "free": True, "text": "Yes"}, {"id": "paid-b", "free": False, "text": "Yes"},
        {"id": "maybe-c", "free": None, "text": "Yes"}, {"id": "whisper-large", "free": True},
        {"id": "embed-text-embedding", "free": True}, {"id": "no-text", "text": "No"}], capabilities=CAPABILITIES)
    api_manager.apply_models(s, "mistral", [{"id": "m-free", "free": True, "text": "Yes"}], capabilities=CAPABILITIES)
    return s


def by_model(rows):
    return {r["model"]: r for r in rows}


class TabRuleTests(unittest.TestCase):
    def test_free_paid_and_unknown_are_never_mixed_up(self):
        rows = by_model(catalog_rows(build()))
        self.assertEqual(rows["free-a"]["tabs"], [mc.TAB_FREE])
        self.assertEqual(rows["paid-b"]["tabs"], [mc.TAB_PAID])
        self.assertEqual(rows["maybe-c"]["tabs"], [mc.TAB_PAID])          # unknown price is NOT shown as free
        self.assertEqual((rows["free-a"]["price"], rows["paid-b"]["price"], rows["maybe-c"]["price"]),
                         ("free", "paid", "unknown"))

    def test_non_chat_models_are_hidden(self):
        rows = by_model(catalog_rows(build()))
        for hidden in ("whisper-large", "embed-text-embedding", "no-text"):
            self.assertNotIn(hidden, rows)

    def test_gemini_4_hydrogen_appears_in_the_free_tab(self):
        s = helpers.fresh_settings()
        pid = routes.add_provider(
            s, "Google AI Studio",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test-google-api-key-1234567890",
        )
        CAPABILITIES.clear()
        api_manager.ensure_registry(s, CAPABILITIES)
        api_manager.apply_models(
            s, pid, [{"id": "gemini-4-hydrogen", "free": True, "text": "Yes"}], capabilities=CAPABILITIES
        )

        row = by_model(catalog_rows(s))["gemini-4-hydrogen"]
        self.assertEqual(row["price"], "free")
        self.assertEqual(row["tabs"], [mc.TAB_FREE])

    def test_identical_models_from_apinex_and_google_share_one_catalog_row(self):
        s = helpers.fresh_settings()
        apinex = routes.add_provider(
            s, "APInex", "https://api.apinex.bond/v1", api_key="test-apinex-key-123456"
        )
        google = routes.add_provider(
            s, "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test-google-key-123456"
        )
        CAPABILITIES.clear()
        api_manager.ensure_registry(s, CAPABILITIES)
        model = "gemenai-4-hydrogen"
        api_manager.apply_models(
            s, apinex, [{"id": "free/" + model, "free": True, "text": "Yes"}],
            capabilities=CAPABILITIES
        )
        api_manager.apply_models(
            s, google, [{"id": "goole/" + model, "free": False, "text": "Yes"}],
            capabilities=CAPABILITIES
        )

        rows = catalog_rows(s)
        matching = [row for row in rows if row["model"].casefold() == model.casefold()]
        self.assertEqual(len(matching), 1)
        group = matching[0]
        self.assertEqual(set(group["provider_ids"]), {apinex, google})
        self.assertEqual(set(group["member_keys"]), {(apinex, "free/" + model), (google, "goole/" + model)})
        self.assertEqual(group["provider_label"], "APInex + Google AI Studio")
        self.assertEqual(group["member_count"], 2)
        self.assertEqual(group["price"], "unknown")  # provider prices differ; never pretend both are free
        self.assertEqual(group["tabs"], [mc.TAB_FREE, mc.TAB_PAID])
        self.assertIn("APInex", group["price_tooltip"])
        self.assertIn("Google AI Studio", group["price_tooltip"])

    def test_grouped_catalog_members_keep_independent_route_ids(self):
        s = helpers.fresh_settings()
        apinex = routes.add_provider(
            s, "APInex", "https://api.apinex.bond/v1", api_key="test-apinex-key-123456"
        )
        google = routes.add_provider(
            s, "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test-google-key-123456"
        )
        CAPABILITIES.clear()
        api_manager.ensure_registry(s, CAPABILITIES)
        model = "gemenai-4-hydrogen"
        api_manager.apply_models(s, apinex, [{"id": "free/" + model, "free": True}], capabilities=CAPABILITIES)
        api_manager.apply_models(s, google, [{"id": "goole/" + model, "free": True}], capabilities=CAPABILITIES)

        group = next(row for row in catalog_rows(s) if row["model"] == model)
        first_provider, first_model = group["member_keys"][0]
        first_route_id = api_manager.set_model_enabled(s, first_provider, first_model, True)
        partially_enabled = next(row for row in catalog_rows(s) if row["model"] == model)
        self.assertTrue(partially_enabled["enabled"])
        self.assertIn(mc.TAB_ACTIVE, partially_enabled["tabs"])

        route_ids = [first_route_id]
        for provider, model_id in group["member_keys"][1:]:
            route_ids.append(api_manager.set_model_enabled(s, provider, model_id, True))

        self.assertEqual(len(set(route_ids)), 2)
        matching_routes = [route for route in routes.get_routes(s) if route["id"] in route_ids]
        self.assertEqual({route["provider"] for route in matching_routes}, {apinex, google})
        self.assertEqual({route["model"] for route in matching_routes}, {"free/" + model, "goole/" + model})
        refreshed = next(row for row in catalog_rows(s) if row["model"] == model)
        self.assertTrue(refreshed["enabled"])
        self.assertIn(mc.TAB_ACTIVE, refreshed["tabs"])
    def test_enabled_route_adds_the_active_tab_and_keeps_its_price_tab(self):
        s = build()
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        row = by_model(catalog_rows(s))["free-a"]
        self.assertEqual(row["tabs"], [mc.TAB_ACTIVE, mc.TAB_FREE])
        self.assertTrue(row["enabled"])

    def test_active_tab_follows_route_priority(self):
        s = build()
        api_manager.set_model_enabled(s, "mistral", "m-free", True)
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        active = mc.rows_for_tab(catalog_rows(s), mc.TAB_ACTIVE)
        self.assertEqual([r["model"] for r in active], ["m-free", "free-a"])

    def test_counts(self):
        s = build()
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        counts = mc.tab_counts(catalog_rows(s))
        self.assertEqual(counts, {"active": 1, "free": 2, "paid": 2, "archived": 0})


    def test_ollama_models_appear_in_unified_catalog_and_can_be_enabled(self):
        s = build()
        added = routes.add_ollama_models(s, ["local-model:latest", "another-local:Q4_K_M"])
        self.assertEqual(len(added), 2)

        rows = by_model(catalog_rows(s))
        local = rows["local-model:latest"]
        self.assertEqual(local["provider"], "ollama")
        self.assertEqual(local["price"], "free")
        self.assertEqual(local["tabs"], [mc.TAB_FREE])
        self.assertFalse(local["enabled"])

        api_manager.set_model_enabled(s, "ollama", "local-model:latest", True)
        enabled = by_model(catalog_rows(s))["local-model:latest"]
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["tabs"], [mc.TAB_ACTIVE, mc.TAB_FREE])

        api_manager.set_model_enabled(s, "ollama", "local-model:latest", False)
        disabled = by_model(catalog_rows(s))["local-model:latest"]
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["tabs"], [mc.TAB_FREE])


class ArchiveTests(unittest.TestCase):
    def test_archive_moves_the_model_and_switches_its_route_off(self):
        s = build()
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        api_manager.set_model_enabled(s, "groq", "paid-b", True)
        mc.archive_model(s, "groq", "free-a")
        row = by_model(catalog_rows(s))["free-a"]
        self.assertEqual(row["tabs"], [mc.TAB_ARCHIVED])
        self.assertFalse(row["enabled"])
        self.assertTrue(row["restorable"])
        self.assertFalse(next(r for r in routes.get_routes(s) if r["model"] == "free-a")["enabled"])    # off, not deleted

    def test_archiving_the_pinned_model_unpins_it(self):
        s = build()
        rid = api_manager.set_model_enabled(s, "groq", "free-a", True)
        s["manual_route_id"] = rid
        mc.archive_model(s, "groq", "free-a")
        self.assertEqual(s["manual_route_id"], "")

    def test_restore_brings_it_back_switched_off(self):
        s = build()
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        mc.archive_model(s, "groq", "free-a")
        mc.restore_model(s, "groq", "free-a", capabilities=CAPABILITIES)
        row = by_model(catalog_rows(s))["free-a"]
        self.assertEqual(row["tabs"], [mc.TAB_FREE])
        self.assertFalse(row["enabled"])

    def test_model_gone_from_the_service_is_archived_and_not_restorable(self):
        s = build()
        api_manager.apply_models(s, "groq", [{"id": "free-a", "free": True, "text": "Yes"}], capabilities=CAPABILITIES)      # the others vanished
        row = by_model(catalog_rows(s))["paid-b"]
        self.assertEqual(row["tabs"], [mc.TAB_ARCHIVED])
        self.assertFalse(row["restorable"])
        self.assertIn("دیگر در سرویس نیست", row["reason"])

    def test_auto_disabled_route_is_archived_until_restored(self):
        s = build()
        api_manager.set_model_enabled(s, "groq", "free-a", True)
        api_manager.set_model_enabled(s, "mistral", "m-free", True)
        rid = next(r["id"] for r in routes.get_routes(s) if r["model"] == "free-a")
        routes.disable_route(
            s, rid, "این مدل دیگر رایگان نیست", capabilities=CAPABILITIES
        )
        row = by_model(catalog_rows(s))["free-a"]
        self.assertEqual(row["tabs"], [mc.TAB_ARCHIVED])
        self.assertIn("خودکار", row["reason"])
        mc.restore_model(s, "groq", "free-a", capabilities=CAPABILITIES)
        self.assertEqual(by_model(catalog_rows(s))["free-a"]["tabs"], [mc.TAB_FREE])

    def test_forget_provider_clears_archive_and_tests(self):
        s = build()
        mc.archive_model(s, "groq", "free-a")
        mc.record_test(s, "groq", "free-a", True, 120, capabilities=CAPABILITIES)
        mc.forget_provider(s, "groq", capabilities=CAPABILITIES)
        self.assertFalse(mc.is_archived(s, "groq", "free-a"))
        self.assertIsNone(mc.test_result(s, "groq", "free-a", capabilities=CAPABILITIES))


class TestResultTests(unittest.TestCase):
    def test_result_is_stored_and_shown_in_the_row(self):
        s = build()
        mc.record_test(s, "groq", "free-a", False, None, "x" * 500, now=1000, capabilities=CAPABILITIES)
        row = by_model(catalog_rows(s))["free-a"]
        self.assertFalse(row["test"]["ok"])
        self.assertEqual(len(row["test"]["message"]), 300)
        self.assertEqual(row["test"]["at"], 1000)
        self.assertIsNone(by_model(catalog_rows(s))["paid-b"]["test"])


if __name__ == "__main__":
    unittest.main()
