"""Pure Chat search value and timestamp contract tests."""
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from kira.domain.search import (
    ChatMessageReference,
    ChatSearchHit,
    ChatSearchPage,
    ChatSearchRequest,
    ChatSearchValidationError,
    message_datetime,
    parse_search_datetime,
    search_snippet,
)


class ChatSearchDomainTests(unittest.TestCase):
    def test_request_and_result_contracts_are_immutable(self):
        request = ChatSearchRequest("hello", character_id="kira")
        with self.assertRaises(FrozenInstanceError):
            request.query = "changed"

        reference = ChatMessageReference("conversation-1", 7)
        hit = ChatSearchHit(
            message_id=7, conversation_id="conversation-1", character_id="kira",
            role="user", content="hello", snippet="hello", created_at="2026-01-01",
            status="complete", reference=reference,
        )
        page = ChatSearchPage(
            query="hello", results=(hit,), total=1, page=1, page_size=20,
            total_pages=1, has_previous=False, has_next=False,
        )
        self.assertEqual(page.as_dict()["results"][0]["reference"], {
            "conversation_id": "conversation-1", "message_id": 7,
        })

    def test_date_bounds_are_normalized_to_utc_and_inclusive_end_of_day(self):
        start = parse_search_datetime("2026-01-01")
        end = parse_search_datetime("2026-01-01", end_of_day=True)
        self.assertEqual(start, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(end.date().isoformat(), "2026-01-01")
        self.assertGreater(end, start)

    def test_invalid_bounds_raise_domain_validation_error(self):
        with self.assertRaises(ChatSearchValidationError):
            parse_search_datetime("not-a-date")

    def test_bad_legacy_message_timestamps_are_non_matching_not_fatal(self):
        self.assertIsNone(message_datetime("legacy-invalid"))
        self.assertEqual(
            message_datetime("2026-01-01T00:00:00Z"),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_snippet_is_bounded_and_centers_the_match(self):
        content = "x" * 200 + "needle" + "y" * 200
        snippet = search_snippet(content, "needle", limit=60)
        self.assertLessEqual(len(snippet), 62)
        self.assertIn("needle", snippet)


if __name__ == "__main__":
    unittest.main()
