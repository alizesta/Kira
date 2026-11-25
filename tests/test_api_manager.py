"""API Manager: provider detection, validation, registration, migration, refresh, delete, priority. Pure logic, HTTP is mocked, test data only."""
from tests.ui_helpers import package_source
import json
import unittest
from copy import deepcopy
from unittest import mock

import requests

from tests import helpers
from kira import api_manager as am
from kira import config, discovery
from kira import routes as rm

GROQ_KEY = "gsk_" + "a" * 40
GOOGLE_KEY = "AIza" + "b" * 35
MISTRAL_KEY = "m" * 32
CF_KEY = "c" * 40


class R:
    def __init__(self, code=200, js=None, headers=None, text=""):
        self.status_code, self._js, self.headers, self.text = code, js, headers or {}, text or json.dumps(js or {})

    def json(self):
        return self._js


class Net:
    """Fake requests.get routed by URL; records every call so tests can prove where a key was (not) sent."""
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(headers or {}), dict(params or {})))
        for part, resp in self.table.items():
            if part in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp(url) if callable(resp) else resp
        return R(404, {})

    def hosts(self):
        return {u.split("/")[2] for u, _, _ in self.calls}


def groq_models():
    return R(200, {"data": [{"id": "openai/gpt-oss-120b", "context_window": 131072, "max_completion_tokens": 65536, "active": True},
                            {"id": "llama-x", "context_window": 8192}, {"id": "whisper-large-v3"}]},
             {"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "999", "content-type": "x"})


def fresh():
    s = deepcopy(config.DEFAULTS)
    rm.ensure_routes(s)
    return s


def run_detect(table, key, **kw):
    net = Net(table)
    with mock.patch.object(discovery.requests, "get", net):
        return am.detect(key, **kw), net


class DetectionTests(unittest.TestCase):
    def test_prefix_decides_candidates_and_key_goes_only_there(self):
        det, net = run_detect({"api.groq.com": groq_models()}, GROQ_KEY)
        self.assertEqual((det.state, det.service), ("ok", "groq"))
        self.assertEqual(net.hosts(), {"api.groq.com"})                                # not sent to any other service
        det, net = run_detect({"generativelanguage": R(200, {"models": []})}, GOOGLE_KEY)
        self.assertEqual(net.hosts(), {"generativelanguage.googleapis.com"})
        self.assertEqual(am.candidate_services(MISTRAL_KEY), ["mistral", "cloudflare"])
        self.assertEqual(am.candidate_services("sk-or-v1-" + "x" * 32), ["openrouter"])
        self.assertEqual(am.candidate_services("AQ." + "x" * 50), ["google"])

    def test_groq_models_carry_only_real_data_and_rate_headers(self):
        det, _ = run_detect({"api.groq.com": groq_models()}, GROQ_KEY)
        by = {m["id"]: m for m in det.models}
        self.assertNotIn("whisper-large-v3", by)                                        # not a chat model
        self.assertEqual((by["openai/gpt-oss-120b"]["context"], by["openai/gpt-oss-120b"]["max_output"]), (131072, 65536))
        self.assertIsNone(by["llama-x"]["max_output"])                                  # not reported -> None, never guessed
        self.assertIsNone(by["llama-x"]["vision"])
        self.assertEqual(det.rate_limit, {"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "999"})

    def test_invalid_key_is_reported_without_leaking_it(self):
        det, _ = run_detect({"api.groq.com": R(401, {})}, GROQ_KEY)
        self.assertEqual(det.state, "invalid")
        self.assertNotIn(GROQ_KEY, det.message)

    def test_google_gemini_discovery_follows_pages_and_filters_non_chat_models(self):
        pages = [
            R(200, {"models": [
                {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash",
                 "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000},
                {"name": "models/imagen-4", "supportedGenerationMethods": ["generateContent"]},
            ], "nextPageToken": "next-page"}),
            R(200, {"models": [
                {"name": "models/gemini-2.5-pro", "displayName": "Gemini 2.5 Pro",
                 "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 2000},
                {"name": "models/gemini-4-hydrogen", "displayName": "Gemini 4 Hydrogen",
                 "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1048576},
            ]}),
        ]
        calls = []
        def get(url, headers=None, params=None, timeout=None):
            calls.append((url, dict(headers or {}), dict(params or {})))
            return pages.pop(0)
        with mock.patch.object(discovery.requests, "get", side_effect=get):
            det = am.detect(GOOGLE_KEY)
        self.assertEqual((det.state, det.service), ("ok", "google"))
        self.assertEqual(
            [m["id"] for m in det.models],
            ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-4-hydrogen"],
        )
        hydrogen = next(m for m in det.models if m["id"] == "gemini-4-hydrogen")
        self.assertTrue(hydrogen["free"])
        self.assertEqual(calls[1][2]["pageToken"], "next-page")
        self.assertEqual(calls[0][1]["x-goog-api-key"], GOOGLE_KEY)
        self.assertNotIn(GOOGLE_KEY, calls[0][0])

    def test_google_wrong_key_is_400_and_key_travels_in_header_not_url(self):
        bad = R(400, {"error": {"message": "API key not valid. Please pass a valid API key."}}, text="API key not valid")
        det, net = run_detect({"generativelanguage": bad}, GOOGLE_KEY)
        self.assertEqual(det.state, "invalid")
        url, headers, params = net.calls[0]
        self.assertEqual(headers.get("x-goog-api-key"), GOOGLE_KEY)
        self.assertNotIn(GOOGLE_KEY, url + json.dumps(params))

    def test_google_models_use_real_limits_and_do_not_guess_capabilities(self):
        body = {"models": [{"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "inputTokenLimit": 1048576,
                            "outputTokenLimit": 65536, "supportedGenerationMethods": ["generateContent"]}]}
        det, _ = run_detect({"generativelanguage": R(200, body)}, GOOGLE_KEY)
        m = det.models[0]
        self.assertEqual((m["context"], m["max_output"], m["text"], m["vision"], m["tools"]), (1048576, 65536, True, None, None))

    def test_unprefixed_key_unknown_when_nobody_accepts_it_and_nothing_is_registered(self):
        det, net = run_detect({"api.mistral.ai": R(401, {}), "api.cloudflare.com": R(401, {"success": False})}, "z" * 30)
        self.assertEqual(det.state, "unknown")
        self.assertEqual(net.hosts(), {"api.mistral.ai", "api.cloudflare.com"})         # only the two prefix-less services were asked
        with self.assertRaises(ValueError):
            am.register(fresh(), det, "z" * 30)

    def test_openrouter_key_is_detected_and_registered_on_builtin(self):
        key = "sk-or-v1-" + "x" * 32
        body = R(200, {"data": [{"id": "meta-llama/llama-3.3-70b-instruct:free",
                                  "architecture": {"input_modalities": ["text"]},
                                  "pricing": {"prompt": "0", "completion": "0"}}]})
        det, net = run_detect({"openrouter.ai": body}, key)
        self.assertEqual((det.state, det.service), ("ok", "openrouter"))
        self.assertEqual(net.hosts(), {"openrouter.ai"})
        self.assertTrue(det.models[0]["free"])
        settings = fresh()
        pid = am.register(settings, det, key)
        self.assertEqual(pid, "openrouter")
        self.assertEqual(settings["providers"][pid]["api_key"], key)
        self.assertEqual(settings["providers"][pid]["base_url"], "https://openrouter.ai/api/v1")

    def test_groq_network_access_denied_is_not_reported_as_invalid_key(self):
        response = R(403, {"error": {"message": "Network access denied"}}, text="Network access denied")
        det, _ = run_detect({"api.groq.com": response}, GROQ_KEY)
        self.assertEqual(det.state, "error")
        self.assertIn("IP", det.message)

    def test_mistral_detected(self):
        body = {"data": [{"id": "mistral-small-latest", "max_context_length": 32768, "capabilities": {"completion_chat": True, "vision": False, "function_calling": True}},
                         {"id": "mistral-embed", "capabilities": {"completion_chat": False}}]}
        det, _ = run_detect({"api.mistral.ai": R(200, body), "api.cloudflare.com": R(403, {})}, MISTRAL_KEY)
        self.assertEqual((det.state, det.service), ("ok", "mistral"))
        m = det.models[0]
        self.assertEqual((m["id"], m["context"], m["text"], m["vision"], m["tools"]), ("mistral-small-latest", 32768, True, False, True))
        self.assertEqual(len(det.models), 1)                                            # embedding model is not a chat model

    def test_cloudflare_account_found_automatically(self):
        search = R(200, {"success": True, "result": [
            {"name": "@cf/meta/llama-3.1-8b-instruct", "task": {"name": "Text Generation"},
             "properties": [{"property_id": "context_window", "value": "7968"}, {"property_id": "function_calling", "value": "true"}]}],
            "result_info": {"total_pages": 1}})
        net = Net({"/user/tokens/verify": R(200, {"success": True, "result": {"status": "active"}}), "/ai/models/search": search,
                   "/client/v4/accounts": R(200, {"result": [{"id": "acc1", "name": "Test"}]}), "api.mistral.ai": R(401, {})})
        with mock.patch.object(discovery.requests, "get", net):
            det = am.detect(CF_KEY)
        self.assertEqual((det.state, det.service, det.account_id), ("ok", "cloudflare", "acc1"))
        self.assertEqual((det.models[0]["context"], det.models[0]["tools"]), (7968, True))

    def test_cloudflare_without_account_permission_asks_for_account_id(self):
        net = Net({"/user/tokens/verify": R(200, {"success": True, "result": {"status": "active"}}), "/client/v4/accounts": R(403, {}), "api.mistral.ai": R(401, {})})
        with mock.patch.object(discovery.requests, "get", net):
            det = am.detect(CF_KEY)
        self.assertEqual(det.state, "needs_account")
        self.assertIn("Account ID", det.message)

    def test_cloudflare_account_scoped_token_requests_account_id_after_user_verify_rejects_it(self):
        net = Net({"/user/tokens/verify": R(401, {"success": False}), "api.mistral.ai": R(401, {})})
        with mock.patch.object(discovery.requests, "get", net):
            det = am.detect(CF_KEY)
        self.assertEqual((det.state, det.service), ("needs_account", "cloudflare"))
        self.assertIn("Account ID", det.message)

    def test_cloudflare_account_id_is_used_to_verify_account_scoped_token(self):
        search = R(200, {"success": True, "result": [
            {"name": "@cf/meta/llama-3.1-8b-instruct", "task": {"name": "Text Generation"}}],
            "result_info": {"total_pages": 1}})
        net = Net({"/accounts/acc1/tokens/verify": R(200, {"success": True, "result": {"status": "active"}}),
                   "/ai/models/search": search})
        with mock.patch.object(discovery.requests, "get", net):
            det = am.detect(CF_KEY, account_id="acc1")
        self.assertEqual((det.state, det.service, det.account_id), ("ok", "cloudflare", "acc1"))
        self.assertTrue(any("/accounts/acc1/tokens/verify" in call[0] for call in net.calls))

    def test_two_services_accepting_one_key_is_ambiguous_and_not_registered(self):
        net = Net({"api.mistral.ai": R(200, {"data": [{"id": "m1"}]}), "/user/tokens/verify": R(200, {"success": True, "result": {"status": "active"}}),
                   "/client/v4/accounts": R(200, {"result": [{"id": "acc1", "name": "x"}]}),
                   "/ai/models/search": R(200, {"success": True, "result": [{"name": "@cf/a", "task": {"name": "Text Generation"}}], "result_info": {"total_pages": 1}})})
        with mock.patch.object(discovery.requests, "get", net):
            det = am.detect(MISTRAL_KEY)
        self.assertEqual(det.state, "ambiguous")
        with self.assertRaises(ValueError):
            am.register(fresh(), det, MISTRAL_KEY)

    def test_network_failure_is_an_error_not_an_invalid_key(self):
        det, _ = run_detect({"api.groq.com": requests.ConnectionError(f"boom {GROQ_KEY}")}, GROQ_KEY)
        self.assertEqual(det.state, "error")
        self.assertNotIn(GROQ_KEY, det.message)

    def test_bad_key_shape_is_rejected_without_any_request(self):
        for bad in ("", "short", "has space " + "x" * 20, "کلید" * 10):
            det, net = run_detect({}, bad)
            self.assertEqual(det.state, "invalid")
            self.assertEqual(net.calls, [])


class RegistrationTests(unittest.TestCase):
    def ok(self, service, models, key, account=""):
        return am.Detection("ok", service, "", models, account_id=account, rate_limit={"x-ratelimit-limit-requests": "5"})

    def test_first_key_reuses_builtin_and_keeps_old_routes_and_priority(self):
        s = fresh()
        rm.reorder(s, ["mistral", "groq", "cloudflare", "openrouter", "ollama"])
        order_before = [r["id"] for r in rm.get_routes(s)]
        models = [{"id": "openai/gpt-oss-120b", "context": 131072}, {"id": "llama-x"}]
        pid = am.register(s, self.ok("groq", models, GROQ_KEY), GROQ_KEY)
        self.assertEqual(pid, "groq")
        self.assertEqual([r["id"] for r in rm.get_routes(s)], order_before)            # nothing moved
        self.assertTrue(s["providers"]["groq"]["enabled"])
        self.assertTrue(rm.find_route(s, "groq")["enabled"])                           # the default model is switched on
        self.assertFalse(any(r["model"] == "llama-x" for r in rm.get_routes(s)))       # other models are listed, not routed, until enabled
        self.assertEqual(am.api_row(s, "groq")["accessible"], 2)

    def test_second_key_of_same_service_is_an_additional_api(self):
        s = fresh()
        am.register(s, self.ok("groq", [{"id": "openai/gpt-oss-120b"}], GROQ_KEY), GROQ_KEY)
        key2 = "gsk_" + "z" * 40
        pid2 = am.register(s, self.ok("groq", [{"id": "openai/gpt-oss-120b"}], key2), key2)
        self.assertNotEqual(pid2, "groq")
        self.assertEqual(rm.provider_label(pid2, s["providers"][pid2]), "Groq (2)")
        self.assertEqual(s["providers"][pid2]["base_url"], am.SERVICES["groq"]["base_url"])
        self.assertEqual(am.unique_models(s)["openai/gpt-oss-120b"], ["groq", pid2])  # ONE model, two ways to reach it
        d = am.api_details(s, pid2)["models"][0]
        self.assertEqual(d["also_on"], ["Groq"])
        self.assertEqual(sum(r["model"] == "openai/gpt-oss-120b" for r in rm.get_routes(s)), 2)    # both routes still exist for failover

    def test_duplicate_key_refused(self):
        s = fresh()
        am.register(s, self.ok("groq", [{"id": "m"}], GROQ_KEY), GROQ_KEY)
        with self.assertRaises(ValueError):
            am.register(s, self.ok("groq", [{"id": "m"}], GROQ_KEY), GROQ_KEY)
        self.assertEqual(am.find_duplicate(s, GROQ_KEY), "groq")

    def test_google_is_registered_with_official_base_url_and_default_model(self):
        s = fresh()
        pid = am.register(s, self.ok("google", [{"id": "gemini-2.5-flash"}, {"id": "gemini-2.5-pro"}], GOOGLE_KEY), GOOGLE_KEY)
        cfg = s["providers"][pid]
        self.assertEqual((cfg["base_url"], cfg["service"], cfg["type"]), (am.SERVICES["google"]["base_url"], "google", "openai_compat"))
        self.assertEqual([r["model"] for r in rm.get_routes(s) if r["provider"] == pid], ["gemini-2.5-flash"])
        self.assertEqual(am.service_of(pid, cfg), "google")
        details = am.api_details(s, pid)
        self.assertEqual({m["id"] for m in details["models"]}, {"gemini-2.5-flash", "gemini-2.5-pro"})
        self.assertEqual(sum(r["provider"] == pid and r["enabled"] for r in rm.get_routes(s)), 1)

    def test_google_registration_moves_gemini_to_first_chat_priority(self):
        s = fresh()
        # Simulate a working Cloudflare route already ahead of Google.
        s["providers"]["cloudflare"].update({"enabled": True, "api_key": CF_KEY, "account_id": "account"})
        rm.update_route(s, "cloudflare", enabled=True)
        pid = am.register(
            s,
            self.ok("google", [{"id": "gemini-3.8-flash"}, {"id": "gemini-3.8-pro"}], GOOGLE_KEY),
            GOOGLE_KEY,
        )
        routes = rm.get_routes(s)
        google_routes = [r for r in routes if r["provider"] == pid]
        self.assertTrue(google_routes)
        self.assertEqual(routes[0]["provider"], pid)
        self.assertEqual(routes[0]["model"], "gemini-3.8-flash")
        self.assertEqual(s["default_route_id"], routes[0]["id"])
        self.assertEqual([r["model"] for r in google_routes], ["gemini-3.8-flash"])

    def test_existing_unkeyed_gemini_provider_is_reused(self):
        s = fresh()
        old = rm.add_provider(s, "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "", False, True)
        rm.add_route(s, old, "gemini-flash-latest")
        pid = am.register(s, self.ok("google", [{"id": "gemini-flash-latest"}], GOOGLE_KEY), GOOGLE_KEY)
        self.assertEqual(pid, old)
        self.assertEqual(s["providers"][old]["api_key"], GOOGLE_KEY)
        self.assertEqual(rm.get_routes(s)[0]["provider"], old)

    def test_second_cloudflare_account_is_a_cloudflare_type_provider_the_engine_can_run(self):
        from kira.hybrid_ai import provider_class, CloudflareProvider
        s = fresh()
        am.register(s, self.ok("cloudflare", [{"id": "@cf/meta/llama-3.1-8b-instruct"}], CF_KEY, "acc1"), CF_KEY)
        k2 = "d" * 40
        pid2 = am.register(s, self.ok("cloudflare", [{"id": "@cf/meta/llama-3.1-8b-instruct"}], k2, "acc2"), k2)
        self.assertIs(provider_class(pid2, s["providers"][pid2]), CloudflareProvider)
        self.assertEqual((s["providers"]["cloudflare"]["account_id"], s["providers"][pid2]["account_id"]), ("acc1", "acc2"))
        self.assertIs(discovery.find_discoverer(pid2, s["providers"][pid2]), discovery._cloudflare)

    def test_registry_never_contains_a_key(self):
        s = fresh()
        am.register(s, self.ok("groq", [{"id": "m1"}], GROQ_KEY), GROQ_KEY)
        self.assertNotIn(GROQ_KEY, json.dumps(s["api_registry"]))
        self.assertNotIn(GROQ_KEY, json.dumps(am.api_rows(s)) + json.dumps(am.api_details(s, "groq")))
        self.assertEqual(am.mask_key(GROQ_KEY), "••••••" + GROQ_KEY[-4:])


class MigrationAndLifecycleTests(unittest.TestCase):
    def old_settings(self):
        s = fresh()
        helpers.enable(s, "groq", "mistral", "cloudflare")
        rm.reorder(s, ["cloudflare", "groq", "mistral", "openrouter", "ollama"])
        s.pop("api_registry", None)
        return s

    def test_old_keys_become_registered_apis_without_network_or_changes(self):
        s = self.old_settings()
        before = deepcopy({k: s[k] for k in ("providers", "routes", "provider_order")})
        with mock.patch.object(discovery.requests, "get", side_effect=AssertionError("no network during migration")):
            rows = am.api_rows(s)
        self.assertEqual({r["id"] for r in rows}, {"groq", "mistral", "cloudflare"})
        self.assertEqual({k: s[k] for k in before}, before)                           # keys, routes, order, models untouched
        self.assertTrue(all(r["status"] == "not validated yet" and r["accessible"] is None and r["checked_at"] == 0 for r in rows))
        self.assertEqual([r["id"] for r in rows], ["cloudflare", "groq", "mistral"])   # priority = the existing route order
        self.assertEqual(am.api_details(s, "groq")["models"][0]["status"], "unknown")

    def test_custom_providers_stay_listed(self):
        s = fresh()
        pid = rm.add_provider(s, "LM Studio", "http://localhost:1234/v1", "", True)
        rm.add_route(s, pid, "qwen-7b")
        self.assertIn(pid, [r["id"] for r in am.api_rows(s)])
        self.assertEqual(am.service_of(pid, s["providers"][pid]), "custom")
        self.assertNotIn("ollama", [r["id"] for r in am.api_rows(s)])                  # the local engine is not an API key

    def test_settings_round_trip_restores_apis_models_and_priority(self):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        prot, unprot = helpers.fake_dpapi()
        with mock.patch.object(config, "CONFIG_PATH", tmp / "settings.json"), mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot):
            s = fresh()
            am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b", "context": 1000}]), GROQ_KEY)
            am.register(s, am.Detection("ok", "mistral", "", [{"id": "mistral-small-latest"}]), MISTRAL_KEY)
            am.move_api(s, "mistral", -1)
            config.save_settings(s)
            raw = (tmp / "settings.json").read_text(encoding="utf-8")
            self.assertNotIn(GROQ_KEY, raw)                                             # encrypted at rest (fake DPAPI)
            loaded = config.load_settings()
        rows = am.api_rows(loaded)
        self.assertEqual([r["id"] for r in rows][:2], ["mistral", "groq"])
        self.assertEqual(loaded["providers"]["groq"]["api_key"], GROQ_KEY)
        self.assertEqual(am.api_details(loaded, "groq")["models"][0]["context"], 1000)
        self.assertIsNot(loaded["api_registry"], config.DEFAULTS["api_registry"])       # DEFAULTS never gets polluted
        self.assertEqual(config.DEFAULTS["api_registry"], {})

    def test_refresh_marks_new_and_vanished_models_and_keeps_routes(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}, {"id": "old-model"}]), GROQ_KEY, )
        am.set_model_enabled(s, "groq", "old-model", True)
        diff = am.apply_models(s, "groq", [{"id": "openai/gpt-oss-120b"}, {"id": "new-model"}], {"retry-after": "3"})
        self.assertEqual((diff["new"], diff["gone"]), (["new-model"], ["old-model"]))
        by = {m["id"]: m for m in am.api_details(s, "groq")["models"]}
        self.assertEqual((by["old-model"]["status"], by["new-model"]["status"]), ("unavailable", "available"))
        self.assertTrue(by["old-model"]["has_route"])                                   # the route is kept; the UI flags it
        self.assertEqual(am.api_details(s, "groq")["rate_limit"], {"retry-after": "3"})

    def test_failed_refresh_keeps_everything_and_records_the_error(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}]), GROQ_KEY)
        am.apply_failure(s, "groq", am.Detection("invalid", "groq", "API Key نامعتبر است (401)."))
        row = am.api_row(s, "groq")
        self.assertEqual((row["status"], row["accessible"]), ("invalid", 1))
        self.assertEqual(s["providers"]["groq"]["api_key"], GROQ_KEY)

    def test_enable_disable_api_gates_the_route_engine(self):
        from kira.hybrid_ai import HybridRouter
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}]), GROQ_KEY)
        router = HybridRouter(s)
        self.assertEqual(router.eligibility(rm.find_route(s, "groq")), (True, "ok"))
        am.set_api_enabled(s, "groq", False)
        self.assertEqual(router.eligibility(rm.find_route(s, "groq")), (False, "provider_off"))
        self.assertEqual(am.api_row(s, "groq")["status"], "disabled")

    def test_model_toggle_creates_and_disables_routes(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}, {"id": "llama-x"}]), GROQ_KEY)
        rid = am.set_model_enabled(s, "groq", "llama-x", True)
        self.assertTrue(rm.find_route(s, rid)["enabled"])
        am.set_model_enabled(s, "groq", "llama-x", False)
        self.assertFalse(rm.find_route(s, rid)["enabled"])
        self.assertEqual(am.api_row(s, "groq")["active"], 1)

    def test_model_toggle_reuses_case_insensitive_existing_route(self):
        s = fresh()
        am.register(
            s,
            am.Detection("ok", "groq", "", [
                {"id": "openai/gpt-oss-120b"},
                {"id": "Case-Sensitive-Model"},
            ]),
            GROQ_KEY,
        )
        route_id = am.set_model_enabled(s, "groq", "Case-Sensitive-Model", True)
        same_id = am.set_model_enabled(s, "groq", "case-sensitive-model", False)
        self.assertEqual(same_id, route_id)
        matching = [
            route for route in rm.get_routes(s)
            if route["provider"] == "groq"
            and route["model"].casefold() == "case-sensitive-model"
        ]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["enabled"])

    def test_delete_builtin_clears_key_disables_routes_custom_is_removed(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}]), GROQ_KEY)
        s["manual_route_id"] = "groq"
        am.delete_api(s, "groq")
        self.assertEqual((s["providers"]["groq"]["api_key"], s["providers"]["groq"]["enabled"]), ("", False))
        self.assertFalse(rm.find_route(s, "groq")["enabled"])
        self.assertEqual(s["manual_route_id"], "")
        self.assertNotIn("groq", [r["id"] for r in am.api_rows(s)])
        pid = am.register(s, am.Detection("ok", "google", "", [{"id": "gemini-2.5-flash"}]), GOOGLE_KEY)
        am.delete_api(s, pid)
        self.assertNotIn(pid, s["providers"])
        self.assertFalse([r for r in rm.get_routes(s) if r["provider"] == pid])
        self.assertNotIn(pid, s["api_registry"])
        self.assertIn("ollama", s["providers"])                                          # local engine untouched
        with self.assertRaises(KeyError):
            am.delete_api(s, "ollama")

    def test_priority_moves_whole_apis_and_keeps_each_models_order(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}, {"id": "a"}, {"id": "b"}]), GROQ_KEY)
        am.set_model_enabled(s, "groq", "a", True)
        am.set_model_enabled(s, "groq", "b", True)
        am.register(s, am.Detection("ok", "mistral", "", [{"id": "mistral-small-latest"}]), MISTRAL_KEY)
        groq_models = [r["model"] for r in rm.get_routes(s) if r["provider"] == "groq"]
        slots_before = [r["provider"] for r in rm.get_routes(s)]
        order = am.move_api(s, "mistral", -1)
        self.assertEqual(order, ["mistral", "groq"])
        self.assertEqual(rm.get_routes(s)[-1]["provider"], "ollama")                       # local engine did not move
        self.assertEqual({r["provider"] for r in rm.get_routes(s)}, set(slots_before))
        self.assertEqual([r["model"] for r in rm.get_routes(s) if r["provider"] == "groq"], groq_models)
        self.assertEqual(s["provider_order"][0], "mistral")                              # legacy mirror updated for older readers
        self.assertEqual(am.api_row(s, "mistral")["priority"], 1)

    def test_unknown_values_are_none_never_invented(self):
        s = fresh()
        am.register(s, am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}]), GROQ_KEY)
        d = am.api_details(s, "groq")
        self.assertIsNone(d["token_usage"])
        self.assertIsNone(d["remaining_quota"])
        self.assertIsNone(d["rate_limit"])
        m = d["models"][0]
        self.assertEqual((m["context"], m["max_output"], m["vision"], m["tools"], m["text"]), (None, None, "Unknown", "Unknown", "Unknown"))

    def test_route_engine_failover_and_cooldown_code_is_untouched(self):
        # the Hybrid Brain / Route Engine API the manager relies on still exists unchanged
        from kira.hybrid_ai import HybridRouter
        for name in ("eligibility", "_candidates", "preview_route", "reset_cooldowns", "_mark_failure", "_execute", "test_route"):
            self.assertTrue(callable(getattr(HybridRouter, name)), name)


class MultiKeyFailoverTests(unittest.TestCase):
    """Two keys of the SAME service: a 429 on the first must fall through to the second without disturbing routes, models or priority."""
    K1, K2 = GROQ_KEY, "gsk_" + "z" * 40

    def setup(self):
        from kira.hybrid_ai import HybridRouter
        s = fresh()
        s["providers"]["ollama"]["enabled"] = False
        det = lambda: am.Detection("ok", "groq", "", [{"id": "openai/gpt-oss-120b"}, {"id": "llama-x"}])    # noqa: E731
        am.register(s, det(), self.K1)
        second = am.register(s, det(), self.K2)
        am.move_api(s, second, -1)                                   # make sure order is explicit: second first, then groq
        am.move_api(s, "groq", -1)                                   # ... and back: groq (key 1) first, key 2 right after
        for r in rm.get_routes(s):
            if r["provider"] not in ("groq", second):
                rm.update_route(s, r["id"], enabled=False)
        return s, second, HybridRouter(s)

    @staticmethod
    def fake(answers):
        used = []

        def post(url, headers=None, json=None, timeout=None, **kw):
            key = headers["Authorization"].split()[-1]
            used.append(key)
            return answers[key].pop(0) if isinstance(answers[key], list) else answers[key]
        post.used = used
        return post

    def test_429_on_key_one_uses_key_two_and_changes_nothing_else(self):
        s, second, router = self.setup()
        snapshot = deepcopy({"routes": rm.get_routes(s), "providers": s["providers"], "order": [r["id"] for r in rm.get_routes(s)]})
        post = self.fake({self.K1: [helpers.Resp(429, {"error": "rate limit"})], self.K2: [helpers.ok_openai("from key two"), helpers.ok_openai("again two")]})
        msgs = [{"role": "user", "content": "hi"}]
        with mock.patch("requests.post", post):
            self.assertEqual(router.chat(msgs, "sys"), "from key two")
            self.assertEqual(post.used, [self.K1, self.K2])
            self.assertIn("groq", router.cooldowns)                                    # only key one's route cools down
            self.assertEqual(set(router.cooldowns), {"groq"})
            self.assertEqual(router.chat(msgs, "sys"), "again two")
            self.assertEqual(post.used[2:], [self.K2])                                  # key one skipped while cooling, no wasted call
        after = {"routes": rm.get_routes(s), "providers": s["providers"], "order": [r["id"] for r in rm.get_routes(s)]}
        self.assertEqual(after, snapshot)                                               # priority, models, enabled flags, keys: identical
        self.assertEqual(router.last_route_id, rm.get_routes(s)[[r["provider"] for r in rm.get_routes(s)].index(second)]["id"])

    def test_key_one_gets_another_chance_after_cooldown_reset_and_order_is_kept(self):
        s, second, router = self.setup()
        post = self.fake({self.K1: [helpers.Resp(429, {"error": "x"}), helpers.ok_openai("one recovered")], self.K2: [helpers.ok_openai("two")]})
        msgs = [{"role": "user", "content": "hi"}]
        with mock.patch("requests.post", post):
            router.chat(msgs, "sys")
            router.reset_cooldowns()
            self.assertEqual(router.chat(msgs, "sys"), "one recovered")                  # priority 1 again, as configured
        self.assertEqual(post.used, [self.K1, self.K2, self.K1])

    def test_quota_exhausted_on_key_one_also_falls_through(self):
        s, second, router = self.setup()
        quota = helpers.Resp(429, {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}})
        post = self.fake({self.K1: [quota], self.K2: [helpers.ok_openai("two")]})
        with mock.patch("requests.post", post):
            self.assertEqual(router.chat([{"role": "user", "content": "hi"}], "sys"), "two")

    def test_disabled_second_api_is_never_used_and_both_failing_reports_error(self):
        s, second, router = self.setup()
        am.set_api_enabled(s, second, False)
        post = self.fake({self.K1: [helpers.Resp(429, {"error": "x"})], self.K2: AssertionError("disabled API must not be called")})
        with mock.patch("requests.post", post):
            with self.assertRaises(Exception):
                router.chat([{"role": "user", "content": "hi"}], "sys")
        self.assertEqual(post.used, [self.K1])


class UiSourceTests(unittest.TestCase):
    """The Qt page cannot run here; its source is checked for the required pieces and for the removed per-provider boxes."""
    def test_route_page_uses_the_api_manager(self):
        from pathlib import Path
        src = package_source()
        for needle in ("Add API", "Registered APIs", "View Details", "Refresh / Rediscover Models", "Enable / Disable", "api_manager.detect",
                       "build_ollama_group", "def api_move", "def api_delete", "def api_edit"):
            self.assertIn(needle, src, needle)
        for needle in ("def api_refresh", "api_manager.rediscover", "def on_api_refreshed", "api_manager.apply_models",
                       "def on_api_model_toggled", "api_manager.set_model_enabled"):
            self.assertIn(needle, src, needle)
        for gone in ("def rebuild_providers", "provider_widgets", "def discover_models_ui", "def begin_provider_edit"):
            self.assertNotIn(gone, src, gone)


if __name__ == "__main__":
    unittest.main()
