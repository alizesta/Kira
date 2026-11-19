"""A 404 that names a replacement model must surface that model to the user."""
import json
import unittest

from kira import hybrid_ai
from kira.hybrid_ai import ProviderError

GOOGLE_404 = {"error": {"code": 404, "status": "NOT_FOUND", "message":
    "This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use "
    "models/gemini-3.8-flash for the latest features and improvements. We recommend you to use the Interactions API."}}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.headers = status, body, {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


def provider(model):
    return hybrid_ai.GroqProvider({"api_key": "k-123456", "model": model})


class ModelReplacementHintTests(unittest.TestCase):
    def raise_for(self, model, body, status=404):
        with self.assertRaises(ProviderError) as cm:
            provider(model)._check_status(FakeResponse(status, body))
        return cm.exception

    def test_google_replacement_is_shown(self):
        err = self.raise_for("gemini-2.5-flash", GOOGLE_404)
        self.assertEqual(err.kind, "model")
        self.assertIn("«gemini-3.8-flash»", str(err))
        self.assertIn("پیشنهاد می‌دهد", str(err))

    def test_no_hint_when_provider_names_no_replacement(self):
        err = self.raise_for("m", {"error": {"message": "model not found"}})
        self.assertEqual(err.kind, "model")
        self.assertNotIn("پیشنهاد می‌دهد", str(err))

    def test_no_hint_when_suggestion_is_the_current_model(self):
        err = self.raise_for("gemini-3.8-flash", {"error": {"message": "please use models/gemini-3.8-flash"}})
        self.assertNotIn("پیشنهاد می‌دهد", str(err))


if __name__ == "__main__":
    unittest.main()


NO_FREE = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message":
    "You exceeded your current quota. Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.5-pro"}}
DAILY = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message":
    "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    "limit: 250, quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}
PER_MINUTE = {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota)."}}


class QuotaExplanationTests(unittest.TestCase):
    def err(self, body):
        with self.assertRaises(ProviderError) as cm:
            provider("gemini-x")._check_status(FakeResponse(429, body))
        return cm.exception

    def test_limit_zero_means_no_free_quota(self):
        e = self.err(NO_FREE)
        self.assertEqual((e.kind, e.quota), ("rate", "no_free"))
        self.assertIn("پلن رایگان", str(e))

    def test_per_day_quota_is_called_daily(self):
        e = self.err(DAILY)
        self.assertEqual(e.quota, "daily")
        self.assertIn("روزانه", str(e))

    def test_plain_rate_limit_stays_unexplained(self):
        e = self.err(PER_MINUTE)
        self.assertEqual((e.kind, e.quota), ("rate", ""))

    def test_no_free_quota_switches_the_route_off_but_daily_does_not(self):
        from kira import routes
        from tests import helpers
        s = helpers.fresh_settings()
        helpers.enable(s, "groq", "mistral")
        routes.ensure_routes(s)
        for rid in [r["id"] for r in routes.get_routes(s)]:
            routes.remove_route(s, rid)
        a = routes.add_route(s, "groq", "gemini-2.5-pro")
        b = routes.add_route(s, "mistral", "other")
        router = hybrid_ai.HybridRouter(s)
        router._mark_failure(b, self.err(DAILY))
        self.assertTrue(routes.find_route(s, b["id"])["enabled"])
        router._mark_failure(a, self.err(NO_FREE))
        self.assertFalse(routes.find_route(s, a["id"])["enabled"])
        self.assertIn("limit: 0", routes.route_note(s, a["id"]))
