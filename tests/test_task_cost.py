"""End-to-end cost of one planned task, driven by a scripted model (no real model, no Windows)."""
import json
import tempfile
import unittest
from pathlib import Path

from kira.tools.access import PathPolicy
from kira.tools.agent import ToolAgent
from kira.tools.builtin import build_registry

PERSONA = "PERSONA-MARKER " + "شخصیت و حافظه‌ی طولانی " * 200        # a long character prompt, as in production


class _Router:
    """Answers each model call from a function of (call number, system prompt); records every prompt."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def chat_stream(self, messages, system_prompt, temperature, on_chunk=None, on_event=None, retry_index=0, **_):
        self.prompts.append(system_prompt)
        text = self.answer(len(self.prompts), system_prompt)
        if on_chunk:
            on_chunk(text)
        return {"text": text, "stopped": False, "interrupted": None}


def _agent(tmp):
    agent = ToolAgent.__new__(ToolAgent)
    agent.settings = {"tools_mode": "auto", "agent_planning": "auto"}
    agent.registry = build_registry(PathPolicy({}))
    agent._competitive_safe_mode = False
    agent._pending_by_session = {}
    agent._pending_new_sessions = set()
    agent._init_session_turn_states()
    agent._init_autonomy(Path(tmp))
    return agent


class PlannedTaskCostTests(unittest.TestCase):
    def _run_single_step_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            real = agent.registry.execute("get_datetime", {}).text
            quote = real.splitlines()[0][:30]
            plan_json = {"goal": "ساعت را بگو", "success_criteria": ["ساعت و تاریخ فعلی خوانده شود"],
                         "steps": [{"id": 1, "title": "خواندن ساعت", "postcondition": "تاریخ و ساعت واقعی برگردد",
                                    "tool": "get_datetime", "depends_on": [], "confirm": False}]}

            def answer(n, system_prompt):
                if "TASK PLANNING (this block" in system_prompt:
                    return "<kira_plan>" + json.dumps(plan_json, ensure_ascii=False) + "</kira_plan>"
                if "FINAL GOAL REVIEW (internal" in system_prompt:
                    return ('<kira_review>{"reviews":[{"step":0,"verdict":"satisfied","reason":"ok","evidence":'
                            + json.dumps([{"criterion": 1, "quote": quote}], ensure_ascii=False) + '}]}</kira_review>')
                if "TASK STEP REVIEW (internal" in system_prompt:
                    return ('<kira_review>{"reviews":[{"step":1,"verdict":"satisfied","reason":"ok","evidence":'
                            + json.dumps(quote, ensure_ascii=False) + '}]}</kira_review>')
                if "TASK EXECUTION (this block" in system_prompt and n == 2:
                    return '<kira_tool>{"tool": "get_datetime", "args": {}, "step": 1}</kira_tool>'
                return "ساعت را خواندم."

            router = _Router(answer)
            plan = agent.plan("ساعت چنده", session_id="kira")
            plan.fast_call = None                       # force the planner path for this measurement
            plan.complex = True
            plan.index_only = False
            result = agent.run(router, [{"role": "user", "content": "ساعت چنده"}], PERSONA, 0.5, plan, on_chunk=lambda s: None)
            return router, result

    def test_review_rounds_do_not_carry_the_character_prompt(self):
        router, result = self._run_single_step_task()
        self.assertEqual(result["text"], "ساعت را خواندم.")
        review_prompts = [p for p in router.prompts if "TASK STEP REVIEW (internal" in p or "FINAL GOAL REVIEW (internal" in p]
        self.assertEqual(len(review_prompts), 2)                     # step review + goal review still happen
        for prompt in review_prompts:
            self.assertNotIn("PERSONA-MARKER", prompt)
        # the rounds that talk to the user keep the personality
        self.assertIn("PERSONA-MARKER", router.prompts[0])
        self.assertIn("PERSONA-MARKER", router.prompts[-1])

    def test_one_step_task_call_count_and_prompt_savings(self):
        router, _ = self._run_single_step_task()
        self.assertEqual(len(router.prompts), 5)                     # plan, run step, review step, review goal, final answer
        total = sum(len(p) for p in router.prompts)
        without_persona = sum(len(p) - len(PERSONA) for p in router.prompts if "PERSONA-MARKER" in p)
        # sanity: two of the five prompts no longer include the long persona text
        self.assertLess(total, 5 * (len(PERSONA) + 12000))
        self.assertGreater(without_persona, 0)


if __name__ == "__main__":
    unittest.main()
