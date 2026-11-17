"""Contract-focused tests for the UI-independent chat search service.

These tests are added for the later integration-test phase; TASK 011 implementation
work intentionally does not execute tests.
"""
import unittest

from kira.chat.search import (
    ChatSearchRepositoryError,
    ChatSearchRequest,
    ChatSearchService,
    ChatSearchValidationError,
)


class MemoryRepository:
    def __init__(self, rows):
        self.rows = list(rows)

    def messages_after(self, after_id=0, limit=500):
        return [row for row in self.rows if row["id"] > after_id][:limit]


class ChatSearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": 1, "role": "user", "content": "Hello there", "created_at": "2026-01-01 10:00:00",
             "character_id": "kira", "conversation_id": "c1", "metadata": {}, "status": "complete"},
            {"id": 2, "role": "assistant", "content": "Hello, this is a longer answer about retrieval.",
             "created_at": "2026-01-02 10:00:00", "character_id": "kira", "conversation_id": "c1",
             "metadata": {"source": "test"}, "status": "complete"},
            {"id": 3, "role": "system", "content": "Search index ready", "created_at": "2026-01-03 10:00:00",
             "character_id": "ren", "conversation_id": "c2", "metadata": {}, "status": "complete"},
            {"id": 4, "role": "user", "content": "retrieval is available", "created_at": "2026-01-04 10:00:00",
             "character_id": "kira", "conversation_id": "c1", "metadata": {}, "status": "complete"},
        ]
        self.service = ChatSearchService(MemoryRepository(self.rows), batch_size=2)

    def test_phrase_search_returns_message_and_conversation_reference(self):
        result = self.service.search("Hello")
        self.assertEqual(result.total, 2)
        self.assertEqual(result.results[0].message_id, 2)
        self.assertEqual(result.results[0].reference.as_dict(),
                         {"conversation_id": "c1", "message_id": 2})

    def test_filters_character_conversation_role_and_time(self):
        result = self.service.search(ChatSearchRequest(
            "retrieval", conversation_id="c1", character_id="kira", roles=("user",),
            start_at="2026-01-04", end_at="2026-01-04", sort_by="oldest",
        ))
        self.assertEqual([hit.message_id for hit in result.results], [4])

    def test_all_terms_mode_and_pagination(self):
        result = self.service.search(ChatSearchRequest(
            "hello retrieval", match_mode="all_terms", page=1, page_size=1,
        ))
        self.assertEqual(result.total, 1)
        self.assertEqual(result.results[0].message_id, 2)
        self.assertEqual(result.total_pages, 1)
        self.assertFalse(result.has_next)

    def test_empty_query_and_invalid_filters_are_rejected(self):
        with self.assertRaises(ChatSearchValidationError):
            self.service.search("   ")
        with self.assertRaises(ChatSearchValidationError):
            self.service.search(ChatSearchRequest("hello", roles=("developer",)))
        with self.assertRaises(ChatSearchValidationError):
            self.service.search(ChatSearchRequest("hello", start_at="2026-02-01", end_at="2026-01-01"))

    def test_empty_result_is_a_valid_empty_page(self):
        result = self.service.search("not present")
        self.assertEqual(result.results, ())
        self.assertEqual(result.total, 0)
        self.assertEqual(result.total_pages, 0)

    def test_repository_failure_is_normalized(self):
        class BrokenRepository:
            def messages_after(self, after_id=0, limit=500):
                raise OSError("storage unavailable")
        with self.assertRaises(ChatSearchRepositoryError):
            ChatSearchService(BrokenRepository()).search("hello")


if __name__ == "__main__":
    unittest.main()
