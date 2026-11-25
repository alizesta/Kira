"""Eye Mode auto screenshot: attach only for screen questions, never while busy, one detail retry."""
import unittest
from types import SimpleNamespace
from unittest import mock

from kira.ui.main_window_chat import ChatController


def make(game_mode=True, busy=False, auto=True, frame={"kind": "image"}):
    ctrl = ChatController.__new__(ChatController)
    session = SimpleNamespace(busy=busy)
    vision = SimpleNamespace(_live_vision_attachment=mock.Mock(return_value=frame))
    ctx = SimpleNamespace(
        session=session,
        state=SimpleNamespace(_game_mode_enabled=game_mode, cur=session, _closing=False),
        services=SimpleNamespace(settings={"eye_auto_screenshot": auto}),
    )
    ctrl.feature_controller = lambda name: vision
    ChatController.context = property(lambda self: ctx)
    return ctrl, ctx, vision


class EyeAutoScreenshotTests(unittest.TestCase):
    def test_attaches_for_screen_question_only(self):
        ctrl, ctx, vision = make()
        self.assertEqual(ctrl._maybe_attach_eye_frame("چی نوشته روی صفحه؟", None), [{"kind": "image"}])
        self.assertEqual(ctx.session._eye_auto_turn["detail"], False)
        self.assertIsNone(ctrl._maybe_attach_eye_frame("سلام چطوری", None))
        self.assertEqual(vision._live_vision_attachment.call_count, 1)

    def test_skips_when_busy_attached_disabled_or_eye_off(self):
        for kwargs in ({"busy": True}, {"game_mode": False}, {"auto": False}):
            ctrl, _, vision = make(**kwargs)
            self.assertIsNone(ctrl._maybe_attach_eye_frame("what does it say on screen", None))
            vision._live_vision_attachment.assert_not_called()
        ctrl, _, vision = make()
        mine = [{"kind": "image", "name": "mine"}]
        self.assertIs(ctrl._maybe_attach_eye_frame("look at this", mine), mine)
        vision._live_vision_attachment.assert_not_called()

    def test_small_text_question_marks_turn_as_detail(self):
        ctrl, ctx, _ = make()
        ctrl._maybe_attach_eye_frame("read the small text on screen", None)
        self.assertTrue(ctx.session._eye_auto_turn["detail"])

    def test_retry_only_once_and_only_when_unreadable(self):
        ctrl, ctx, _ = make()
        ctx.session._eye_auto_turn = {"text": "look at screen", "detail": True}
        with mock.patch("kira.ui.main_window_chat.QTimer") as timer:
            ctrl.maybe_retry_eye_detail("the text is too small")
            timer.singleShot.assert_not_called()          # already at detail size: no loop
            ctx.session._eye_auto_turn = {"text": "look at screen", "detail": False}
            ctrl.maybe_retry_eye_detail("یه دشمن سمت چپه")
            timer.singleShot.assert_not_called()          # readable reply: no retry
            ctx.session._eye_auto_turn = {"text": "look at screen", "detail": False}
            ctrl.maybe_retry_eye_detail("the text is too small to read")
            timer.singleShot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
