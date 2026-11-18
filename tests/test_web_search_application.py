"""Qt-free tests for Web Search application policy."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kira.app.web_search import WebSearchApplicationService


class _ChatClient:
    def __init__(self, response="Query: \"better search\""):
        self.response = response
        self.calls = []

    def chat(self, messages, prompt, temperature):
        self.calls.append((messages, prompt, temperature))
        return self.response


class WebSearchApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = WebSearchApplicationService()

    def test_ui_adapter_methods_keep_websearch_engine_details_inside_service(self):
        result = {"query": "test", "results": []}
        diagnostic = {"engines": {"tavily": {"ok": True}}}
        with patch("kira.app.web_search.websearch.diagnose", return_value=diagnostic) as diagnose:
            self.assertIs(
                self.service.diagnose("key", "basic", "probe", ("gemini-key", "gemini-model")),
                diagnostic,
            )
            diagnose.assert_called_once_with(
                "key", "basic", "probe", ("gemini-key", "gemini-model")
            )

        with patch("kira.app.web_search.websearch.format_block", return_value="[evidence]") as format_block:
            self.assertEqual(self.service.format_evidence(result), "[evidence]")
            format_block.assert_called_once_with(result)

        with patch("kira.app.web_search.websearch.failure_reply", return_value="no result") as failure_reply:
            self.assertEqual(self.service.failure_reply("offline"), "no result")
            failure_reply.assert_called_once_with("offline")

    def test_command_parsers_and_engine_labels_are_exposed_by_service(self):
        with patch(
            "kira.app.web_search.websearch.plan",
            return_value=("web query", True),
        ) as web_parser:
            self.assertEqual(self.service.parse_web_command("/web query"), ("web query", True))
            web_parser.assert_called_once_with("/web query")
        with patch(
            "kira.app.web_search.websearch.image_command",
            return_value=("image hint", True),
        ) as image_parser:
            self.assertEqual(self.service.parse_image_command("/img image hint"), ("image hint", True))
            image_parser.assert_called_once_with("/img image hint")

        self.assertTrue(self.service.engine_label("tavily"))
        self.assertEqual(self.service.engine_label("unknown"), "وب")

    def test_gemini_credentials_resolve_configured_provider_and_model(self):
        settings = {
            "providers": {
                "google": {
                    "base_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "  secret  ",
                }
            },
            "routes": [{"provider": "google", "model": "models/gemini-2.5-flash"}],
        }

        self.assertEqual(
            self.service.gemini_credentials(settings),
            ("secret", "gemini-2.5-flash"),
        )

    def test_gemini_credentials_ignore_unconfigured_or_non_google_providers(self):
        self.assertIsNone(
            self.service.gemini_credentials(
                {"providers": {"local": {"base_url": "http://localhost", "api_key": "x"}}}
            )
        )

    def test_search_query_rewriting_uses_recent_context_and_sanitizes_model_output(self):
        client = _ChatClient('Query: "better search"')
        history = [{"role": "user", "content": str(index)} for index in range(9)]

        result = self.service.make_search_query(history, "literal query", client)

        self.assertEqual(result, "better search")
        self.assertEqual(client.calls[0][0], history[-6:])
        self.assertEqual(client.calls[0][2], 0.1)

    def test_invalid_search_query_rewrite_preserves_literal_query(self):
        client = _ChatClient("x")

        self.assertEqual(
            self.service.make_search_query([], "literal Persian query", client),
            "literal Persian query",
        )

    def test_plan_request_uses_application_policy_and_respects_tool_precedence(self):
        with patch(
            "kira.app.web_search.websearch.plan",
            return_value=("automatic query", False),
        ) as planner:
            self.assertEqual(
                self.service.plan_request("ordinary message", {"web_search": True}),
                ("automatic query", False),
            )
            self.assertEqual(
                self.service.plan_request(
                    "open a local file",
                    {"web_search": True},
                    SimpleNamespace(strong=True, web=False),
                ),
                (None, False),
            )
            self.assertEqual(
                self.service.plan_request(
                    "research this",
                    {"web_search": True},
                    SimpleNamespace(strong=False, web=True),
                ),
                (None, False),
            )
            self.assertEqual(planner.call_count, 3)

    def test_plan_request_obeys_disabled_and_slash_command_rules(self):
        with patch(
            "kira.app.web_search.websearch.plan",
            return_value=("explicit query", True),
        ) as planner:
            self.assertEqual(
                self.service.plan_request("normal", {"web_search": False}),
                (None, False),
            )
            planner.assert_not_called()
            self.assertEqual(
                self.service.plan_request("/web exact phrase", {"web_search": False}),
                ("explicit query", True),
            )
            planner.assert_called_once_with("/web exact phrase")

    def test_explicit_web_request_bypasses_tool_precedence_and_caps_query(self):
        literal = "  " + ("literal " * 60) + "  "
        with patch("kira.app.web_search.websearch.plan") as planner:
            query, forced = self.service.plan_request(
                literal,
                {"web_search": False},
                SimpleNamespace(strong=True, web=True),
                force_web=True,
            )

        self.assertEqual(query, literal.strip()[:300])
        self.assertTrue(forced)
        planner.assert_not_called()

    def test_web_search_options_preserve_literal_query_and_create_followup_rewrite(self):
        client = _ChatClient("resolved query")
        history = [{"role": "user", "content": "earlier context"}]
        settings = {
            "tavily_api_key": " tavily-secret ",
            "web_fallback": True,
            "web_depth": "advanced",
            "providers": {},
        }

        options = self.service.web_search_options(settings, "نه بهتر سرچ کن", history, client)

        self.assertTrue(options.available)
        self.assertEqual(options.api_key, "tavily-secret")
        self.assertEqual(options.depth, "advanced")
        self.assertEqual(options.user_text, "نه بهتر سرچ کن")
        self.assertEqual(options.rewrite(), "resolved query")

    def test_can_search_reflects_tavily_key_and_fallback_policy(self):
        self.assertTrue(self.service.can_search({"tavily_api_key": "key", "web_fallback": False}))
        self.assertTrue(self.service.can_search({"web_fallback": True}))
        self.assertFalse(self.service.can_search({"web_fallback": False}))

    def test_web_search_is_unavailable_without_key_or_fallback(self):
        options = self.service.web_search_options(
            {"web_fallback": False}, "query", [], _ChatClient()
        )
        self.assertFalse(options.available)

    def test_image_search_options_preserve_images_and_description_callback(self):
        client = _ChatClient("a red bicycle")
        images = [{"kind": "image", "b64": "abc"}]
        options = self.service.image_search_options(
            {"tavily_api_key": "key", "web_fallback": True, "web_depth": "basic"},
            "what is this?",
            images,
            client,
        )

        self.assertEqual(options.query, "what is this?")
        self.assertEqual(options.images, tuple(images))
        self.assertEqual(options.describe(), "a red bicycle")
        self.assertEqual(client.calls[0][0][0]["images"], images)

    def test_merge_search_content_preserves_prepared_files_and_image_payload(self):
        base = {"text": "", "files": [{"name": "notes.txt"}], "other": "preserved"}

        result = self.service.merge_search_content(
            base, [{"kind": "image"}], "search evidence", image_search=True
        )

        self.assertEqual(result["other"], "preserved")
        self.assertEqual(result["files"], base["files"])
        self.assertEqual(result["images"], [{"kind": "image"}])
        self.assertTrue(result["search"])
        self.assertIn("این تصویر چیست؟", result["text"])
        self.assertIn("search evidence", result["text"])

    def test_merge_search_content_keeps_legacy_plain_text_shape(self):
        result = self.service.merge_search_content("hello", [], "evidence")
        self.assertEqual(result, {"model": "hello\n\nevidence", "images": []})

    def test_assessment_text_reports_verified_and_unverified_sources(self):
        self.assertIn(
            "منبع 1، 3",
            self.service.assessment_text({"phrase": "exact words", "matched": [1, 3]}),
        )
        self.assertIn(
            "هیچ‌کدام",
            self.service.assessment_text({"phrase": "exact words", "matched": [], "checked": 4}),
        )
        self.assertEqual(self.service.assessment_text(None), "")


if __name__ == "__main__":
    unittest.main()
