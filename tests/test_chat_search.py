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
             "character_id": "kira", "conversation_id": "c1", "metadata": {"session_id": "s1"}, "status": "complete"},
            {"id": 2, "role": "assistant", "content": "Hello, this is a longer answer about retrieval.",
             "created_at": "2026-01-02 10:00:00", "character_id": "kira", "conversation_id": "c1",
             "metadata": {"source": "test", "session_id": "s1"}, "status": "complete"},
            {"id": 3, "role": "system", "content": "Search index ready", "created_at": "2026-01-03 10:00:00",
             "character_id": "ren", "conversation_id": "c2", "metadata": {"session_id": "s2"}, "status": "complete"},
            {"id": 4, "role": "user", "content": "retrieval is available", "created_at": "2026-01-04 10:00:00",
             "character_id": "kira", "conversation_id": "c1", "metadata": {"session_id": "s1"}, "status": "complete"},
        ]
        self.service = ChatSearchService(MemoryRepository(self.rows), batch_size=2)

    def test_phrase_search_returns_message_and_conversation_reference(self):
        result = self.service.search("Hello")
        self.assertEqual(result.total, 2)
        self.assertEqual(result.results[0].message_id, 2)
        self.assertEqual(result.results[0].reference.as_dict(),
                         {"conversation_id": "c1", "message_id": 2})

    def test_exact_mode_matches_the_complete_message_only(self):
        result = self.service.search(ChatSearchRequest("Hello there", match_mode="exact"))
        self.assertEqual([hit.message_id for hit in result.results], [1])

    def test_filters_character_conversation_role_and_time(self):
        result = self.service.search(ChatSearchRequest(
            "retrieval", conversation_id="c1", character_id="kira", roles=("user",),
            start_at="2026-01-04", end_at="2026-01-04", sort_by="oldest",
        ))
        self.assertEqual([hit.message_id for hit in result.results], [4])

    def test_runtime_session_filter_is_independent_of_conversation_filter(self):
        result = self.service.search(ChatSearchRequest("Hello", session_id="s1"))
        self.assertEqual([hit.message_id for hit in result.results], [2, 1])

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

    def test_conversation_status_filter_uses_persisted_conversation_state(self):
        class StatusRepository(MemoryRepository):
            def list_conversations(self, character_id=None):
                rows = [
                    {"id": "c1", "character_id": "kira", "status": "active"},
                    {"id": "c2", "character_id": "ren", "status": "archived"},
                ]
                return [row for row in rows if character_id is None or row["character_id"] == character_id]

        service = ChatSearchService(StatusRepository(self.rows), batch_size=2)
        archived = service.search(ChatSearchRequest(
            "Search", conversation_statuses=("archived",)
        ))
        self.assertEqual([hit.message_id for hit in archived.results], [3])

        active = service.search(ChatSearchRequest(
            "retrieval", conversation_statuses=("active",), character_id="kira"
        ))
        self.assertEqual([hit.message_id for hit in active.results], [4, 2])

    def test_status_filter_requires_repository_conversation_listing(self):
        class MessageOnlyRepository:
            def messages_after(self, after_id=0, limit=500):
                return []

        with self.assertRaises(ChatSearchRepositoryError):
            ChatSearchService(MessageOnlyRepository()).search(
                ChatSearchRequest("query", conversation_statuses=("archived",))
            )

    def test_repository_failure_is_normalized(self):
        class BrokenRepository:
            def messages_after(self, after_id=0, limit=500):
                raise OSError("storage unavailable")
        with self.assertRaises(ChatSearchRepositoryError):
            ChatSearchService(BrokenRepository()).search("hello")


if __name__ == "__main__":
    unittest.main()
