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
