"""Qt-free tests for Coding Agent application handoff."""
import unittest
from unittest.mock import Mock

from kira.app.coding_agent_application import KodeApplicationService, CodingAgentApplicationService


class CodingAgentApplicationServiceTests(unittest.TestCase):
    def test_kode_service_is_the_canonical_name_with_legacy_alias(self):
        self.assertIs(KodeApplicationService, CodingAgentApplicationService)
    def test_attachment_free_turn_is_handed_to_agent_and_chat_request_completed(self):
        agent = Mock()
        agent.handle.return_value = True
        complete = Mock()

        handled = CodingAgentApplicationService.dispatch(
            code_chat=agent, text="inspect this project", voice=True,
            attachments=(), request_id="request-1",
            complete_local_request=complete,
        )

        self.assertTrue(handled)
        agent.handle.assert_called_once_with("inspect this project", True)
        complete.assert_called_once_with("request-1")

    def test_attachments_bypass_agent_and_preserve_normal_chat_flow(self):
        agent = Mock()
        complete = Mock()

        handled = CodingAgentApplicationService.dispatch(
            code_chat=agent, text="describe this", voice=False,
            attachments=({"kind": "image"},), request_id="request-2",
            complete_local_request=complete,
        )

        self.assertFalse(handled)
        agent.handle.assert_not_called()
        complete.assert_not_called()

    def test_unhandled_turn_falls_through_without_completing_chat_request(self):
        agent = Mock()
        agent.handle.return_value = False
        complete = Mock()

        handled = CodingAgentApplicationService.dispatch(
            code_chat=agent, text="hello", voice=False,
            attachments=(), request_id="request-3",
            complete_local_request=complete,
        )

        self.assertFalse(handled)
        complete.assert_not_called()

    def test_agent_session_stop_is_safe_when_session_is_missing(self):
        agent = Mock()
        self.assertFalse(CodingAgentApplicationService.stop_session(agent, None))
        agent.stop.assert_not_called()

    def test_agent_session_stop_delegates_to_existing_owner(self):
        agent = Mock()
        session = object()
        self.assertTrue(CodingAgentApplicationService.stop_session(agent, session))
        agent.stop.assert_called_once_with(session)


if __name__ == "__main__":
    unittest.main()
