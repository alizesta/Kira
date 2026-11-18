"""Pure Chat request/response domain contract tests."""
import unittest
from dataclasses import FrozenInstanceError

from kira.domain.chat import (
    ApplicationEventKind,
    ChatApplicationEvent,
    ChatApplicationRequest,
    ChatRequest,
    ChatResponseResult,
    ProviderEvent,
    ProviderEventKind,
    RequestStatus,
    ResponseError,
    ResponseEventKind,
    ResponseStatus,
    ResponseStreamEvent,
    SubmissionResult,
)


class ChatDomainContractTests(unittest.TestCase):
    def test_chat_request_requires_request_and_session_identity_together(self):
        with self.assertRaises(ValueError):
            ChatRequest("hello", request_id="request-1")
        with self.assertRaises(ValueError):
            ChatRequest("hello", session_id="session-1")

        request = ChatRequest.create(
            "hello", request_id="request-1", session_id="session-1"
        )
        self.assertEqual(request.request_id, "request-1")
        self.assertEqual(request.session_id, "session-1")

    def test_application_request_is_scoped_and_immutable(self):
        request = ChatApplicationRequest(
            request_id="r1", session_id="s1", text="hello",
            conversation_id="c1", character_id="ren",
        )
        self.assertEqual((request.session_id, request.character_id), ("s1", "ren"))
        with self.assertRaises(FrozenInstanceError):
            request.text = "changed"

    def test_provider_event_factories_preserve_request_session_identity(self):
        event = ProviderEvent.chunk("r1", "s1", "chunk")
        self.assertEqual(event.kind, ProviderEventKind.CHUNK)
        self.assertEqual((event.request_id, event.session_id), ("r1", "s1"))
        self.assertEqual(event.payload, "chunk")

    def test_response_and_application_events_use_domain_contracts(self):
        error = ResponseError("provider_error", "offline", recoverable=True)
        result = ChatResponseResult(
            request_id="r1", session_id="s1", status=ResponseStatus.FAILED,
            content="partial", error=error,
        )
        response_event = ResponseStreamEvent(
            request_id="r1", session_id="s1", kind=ResponseEventKind.FINAL,
            content="partial", result=result,
        )
        app_event = ChatApplicationEvent(
            request_id="r1", session_id="s1",
            kind=ApplicationEventKind.REQUEST_FAILED,
            status=RequestStatus.FAILED, result=response_event.result,
        )
        self.assertEqual(app_event.result.error.code, "provider_error")
        self.assertTrue(app_event.result.error.recoverable)

    def test_submission_result_contract_has_expected_admission_states(self):
        self.assertEqual(
            {item.value for item in SubmissionResult},
            {"dispatched", "queued", "full"},
        )


if __name__ == "__main__":
    unittest.main()
