"""Structural contract tests for application-to-application boundaries."""
import unittest

from kira.chat.session_manager import SessionManager
from kira.chat_sessions import ChatSession
from kira.core.interfaces.conversation_lifecycle import ConversationLifecycleApplicationPort
from kira.chat.conversation_lifecycle import ConversationLifecycleService
from kira.core.interfaces.application_services import (
    ApplicationEventPublisherPort,
    ChatApplicationPort,
    RuntimeSessionPort,
    SessionManagerPort,
)


class _ChatApplication:
    def get_or_create_conversation(self, character_id):
        return {"id": character_id}

    def has_active_request(self, session_id):
        return False

    def has_pending_work(self, session_id):
        return False


class _EventPublisher:
    def publish(self, event_type, **payload):
        return None


class ApplicationServicePortTests(unittest.TestCase):
    def test_session_manager_and_session_implement_core_ports(self):
        manager = SessionManager(ChatSession)
        session = manager.create_session("kira")
        self.assertIsInstance(manager, SessionManagerPort)
        self.assertIsInstance(session, RuntimeSessionPort)

    def test_conversation_lifecycle_service_implements_core_port(self):
        class Repository:
            def get_conversation(self, conversation_id):
                return None

            def list_conversations(self, character_id=None):
                return []

            def update_conversation_lifecycle(self, changes):
                return True

            def delete_conversation(self, conversation_id, *, expected_status=None):
                return 0

        class Publisher:
            def publish(self, event_type, **payload):
                return None

        service = ConversationLifecycleService(Repository(), Publisher())
        self.assertIsInstance(service, ConversationLifecycleApplicationPort)

    def test_chat_application_and_event_publisher_implement_core_ports(self):
        self.assertIsInstance(_ChatApplication(), ChatApplicationPort)
        self.assertIsInstance(_EventPublisher(), ApplicationEventPublisherPort)


if __name__ == "__main__":
    unittest.main()
