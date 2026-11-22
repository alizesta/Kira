"""Single-call bridge: native tools from the first call, no triage / planner round trips for ordinary requests."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira.tools import fast_commands
from kira.tools.agent import ToolAgent


class _NativeRouter:
    """Scripted native-function-calling route; records every model call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.native_prompts = []
        self.stream_calls = 0

    def chat_with_tools(self, messages, prompt, temperature, tools, on_event=None):
        self.native_prompts.append(prompt)
        return self.replies.pop(0)

    def chat_stream(self, *args, **kwargs):
        self.stream_calls += 1
        raise AssertionError("native route must not fall back to the text protocol")


class _TextOnlyRouter:
    def chat_stream(self, *args, **kwargs):
        raise AssertionError("not called in this test")


def _call(tool, args=None):
    return {"text": "", "tool_calls": [{"id": "c1", "tool": tool, "args": args or {}}]}


class SingleCallBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent = ToolAgent({"tools_mode": "auto"}, data_dir=Path(self.tmp.name), program_root=Path("."))

    def _run(self, text, router, agent=None):
        agent = agent or self.agent
        plan = agent.plan(text, session_id="kira")
        self.assertIsNotNone(plan)
        chunks = []
        result = agent.run(router, [{"role": "user", "content": text}], "system", 0.2, plan, on_chunk=chunks.append)
        return plan, result, chunks

    def test_unrecognised_wording_skips_triage_and_planner_and_uses_one_model_call(self):
        router = _NativeRouter(_call("get_datetime"))
        plan, result, chunks = self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertTrue(plan.direct)
        self.assertFalse(plan.index_only)
        self.assertFalse(plan.complex)
        self.assertEqual(len(router.native_prompts), 1)
        self.assertEqual(router.stream_calls, 0)
        self.assertTrue(result["text"].startswith("✅"))
        self.assertEqual(chunks, [result["text"]])

    def test_native_prompt_is_the_compact_block_not_the_full_text_catalog(self):
        router = _NativeRouter(_call("get_datetime"))
        self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        prompt = router.native_prompts[0]
        self.assertIn("PC ACCESS", prompt)
        self.assertNotIn("<kira_tool>", prompt)
        self.assertLess(len(prompt), 3000)

    def test_plain_conversation_is_answered_in_the_same_single_call(self):
        router = _NativeRouter({"text": "سلام! حالم خوبه 😊", "tool_calls": []})
        _, result, _ = self._run("اوضاع چطوره", router)
        self.assertEqual(result["text"], "سلام! حالم خوبه 😊")
        self.assertEqual(len(router.native_prompts), 1)

    def test_tool_without_self_explanatory_output_still_gets_a_follow_up_call(self):
        router = _NativeRouter(_call("get_datetime"), {"text": "الان ساعت ۱۶ است.", "tool_calls": []})
        with mock.patch.object(fast_commands, "is_direct_result_tool", return_value=False):
            _, result, _ = self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertEqual(len(router.native_prompts), 2)
        self.assertEqual(result["text"], "الان ساعت ۱۶ است.")

    def test_two_calls_in_one_round_are_not_shown_raw(self):
        both = {"text": "", "tool_calls": [{"id": "a", "tool": "get_datetime", "args": {}},
                                           {"id": "b", "tool": "get_system_info", "args": {}}]}
        router = _NativeRouter(both, {"text": "خلاصه", "tool_calls": []})
        _, result, _ = self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertEqual(len(router.native_prompts), 2)
        self.assertEqual(result["text"], "خلاصه")

    def test_unknown_tool_is_reported_to_the_model_and_nothing_is_shown_raw(self):
        router = _NativeRouter(_call("no_such_tool"), {"text": "این ابزار وجود ندارد.", "tool_calls": []})
        _, result, _ = self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertEqual(len(router.native_prompts), 2)
        self.assertEqual(result["text"], "این ابزار وجود ندارد.")

    def test_bridge_is_not_used_without_native_function_calling(self):
        plan = self.agent.plan("یه چیزی بگو ببینم ساعت رو بیار", session_id="kira")
        self.assertFalse(self.agent._direct_bridge(_TextOnlyRouter(), plan))

    def test_setting_can_restore_the_old_path(self):
        agent = ToolAgent({"tools_mode": "auto", "agent_single_call": "off"},
                          data_dir=Path(self.tmp.name), program_root=Path("."))
        plan = agent.plan("یه چیزی بگو ببینم ساعت رو بیار", session_id="kira")
        self.assertFalse(agent._direct_bridge(_NativeRouter(), plan))

    def test_resumed_task_keeps_the_planner(self):
        plan = self.agent.plan("یه چیزی بگو ببینم ساعت رو بیار", session_id="kira")
        plan.resume = True
        self.assertFalse(self.agent._direct_bridge(_NativeRouter(), plan))

    def test_fast_path_commands_are_untouched(self):
        plan = self.agent.plan("ساعت چنده", session_id="kira")
        self.assertIsNotNone(plan.fast_call)
        self.assertFalse(self.agent._direct_bridge(_NativeRouter(), plan))

    def test_direct_turn_does_not_take_the_web_lock_for_non_web_tools(self):
        class Probe:
            acquires = 0

            def acquire(self, timeout=None):
                Probe.acquires += 1
                return True

            def release(self):
                pass

        self.agent._web_research_lock = Probe()
        router = _NativeRouter(_call("get_datetime"))
        self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertEqual(Probe.acquires, 0)

    def test_web_tool_called_from_a_direct_turn_takes_the_lock_only_around_the_tool(self):
        events = []

        class Probe:
            def acquire(self, timeout=None):
                events.append("acquire")
                return True

            def release(self):
                events.append("release")

        self.agent._web_research_lock = Probe()
        real_execute = self.agent.registry.execute

        def fake_execute(name, args):
            events.append("execute:" + name)
            return real_execute("get_datetime", {})

        router = _NativeRouter(_call("web_search", {"query": "x"}), {"text": "ok", "tool_calls": []})
        with mock.patch.object(self.agent.registry, "execute", side_effect=fake_execute):
            self._run("یه چیزی بگو ببینم ساعت رو بیار", router)
        self.assertEqual(events, ["acquire", "execute:web_search", "release"])


if __name__ == "__main__":
    unittest.main()
