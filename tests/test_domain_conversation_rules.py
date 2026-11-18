"""Pure tests for Conversation lifecycle domain invariants."""
import unittest

from kira.domain.conversations import (
    ConversationOperation,
    ConversationStatus,
    InvalidConversationTransition,
    allowed_source_statuses,
    is_transition_allowed,
)


class ConversationDomainRuleTests(unittest.TestCase):
    def test_archive_restore_trash_and_restore_from_trash_rules(self):
        expected = {
            ConversationOperation.ARCHIVE: (ConversationStatus.ACTIVE,),
            ConversationOperation.RESTORE: (ConversationStatus.ARCHIVED,),
            ConversationOperation.TRASH: (
                ConversationStatus.ACTIVE,
                ConversationStatus.ARCHIVED,
                ConversationStatus.CLOSED,
            ),
            ConversationOperation.RESTORE_TRASHED: (ConversationStatus.TRASHED,),
            ConversationOperation.PERMANENT_DELETE: (ConversationStatus.TRASHED,),
        }
        for operation, sources in expected.items():
            with self.subTest(operation=operation):
                self.assertEqual(allowed_source_statuses(operation), sources)

    def test_transition_decisions_are_pure_and_deterministic(self):
        self.assertTrue(is_transition_allowed(
            ConversationStatus.ACTIVE, ConversationOperation.ARCHIVE
        ))
        self.assertFalse(is_transition_allowed(
            ConversationStatus.TRASHED, ConversationOperation.ARCHIVE
        ))
        self.assertTrue(is_transition_allowed(
            ConversationStatus.CLOSED, ConversationOperation.TRASH
        ))
        self.assertFalse(is_transition_allowed(
            ConversationStatus.ACTIVE, ConversationOperation.PERMANENT_DELETE
        ))

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(ValueError):
            allowed_source_statuses("purge")


if __name__ == "__main__":
    unittest.main()
