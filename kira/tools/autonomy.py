"""Model-driven task autonomy for ToolAgent: planning, execution, semantic review and replanning.

Exact deterministic one-shot commands keep their Fast Path. Other tool-relevant
requests are classified by the selected model using the user's goal, context and
tool catalog rather than task-specific verb rules. Successful tool execution
is not accepted as proof of goal completion: the model compares real outputs
with explicit success criteria and per-step postconditions. The central registry
continues to enforce permissions, confirmations and execution safety.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from . import protocol, planner
from .registry import ToolResult, NEEDS_CONFIRM, BAD_ARGS, DENIED, OK, ERROR, READ, SENSITIVE, clip
from .tasks import (TaskStore, TaskPlan, Step, call_sig, classify_error, summarize_result, parse_control, _safe,
                    PENDING, RUNNING, REVIEW, DONE, FAILED, UNMET, SKIPPED, AWAITING,
                    P_PLANNING, P_RUNNING, P_WAIT_USER, P_WAIT_CONFIRM, P_PAUSED, P_DONE, P_FAILED, P_CANCELLED, P_SUPERSEDED,
                    STEP_MAX_ATTEMPTS, FAIL_SIG_MAX)

_LOGGER = logging.getLogger(__name__)

_PREF_TASK_RX = re.compile(r"(?:همیشه|هر\s*بار|از\s*این\s*به\s*بعد)\s+(.{6,140})", re.I)
_PREF_TASK_TOPIC = re.compile(r"گزارش|مرتب|فایل|پوشه|پیدا|لیست|فهرست|بپرس|تأیید|تایید|خلاصه|کوتاه|جزئیات", re.I)


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


class AutonomyMixin:
    # ------------------------------------------------------------------ setup / settings
    def _init_autonomy(self, data_dir):
        self.tasks = TaskStore(data_dir)
        self._running_plan_sessions: set[str] = set()
        self._turn_plan_ids: dict[str, str] = {}
        self._resume_sessions: set[str] = set()
        self._pause_requests: set[str] = set()
        self._cancel_plan_requests: set[str] = set()

    def planning_enabled(self) -> bool:
        return str(self.settings.get("agent_planning", "auto")).lower() != "off"

    def max_steps(self) -> int:
        return _clamp(self.settings.get("agent_max_steps", 8), 2, 15, 8)

    def max_replans(self) -> int:
        return _clamp(self.settings.get("agent_max_replans", 3), 0, 5, 3)

    def clear_tasks(self, session_id: str | None = None):
        """Clear task history globally or only for one character session."""
        self.tasks.clear(session_id)
        if session_id is None:
            self._resume_sessions.clear()
            self._pause_requests.clear()
            self._cancel_plan_requests.clear()
            self._turn_plan_ids.clear()
        else:
            owner = str(session_id)
            self._resume_sessions.discard(owner)
            self._pause_requests.discard(owner)
            self._cancel_plan_requests.discard(owner)
            self._turn_plan_ids.pop(owner, None)

    def _turn_reset(self):
        owner = getattr(self, "_turn_session_id", "")
        self._turn_plan_ids.pop(owner, None)
        self._pause_requests.discard(owner)
        self._cancel_plan_requests.discard(owner)

    # ------------------------------------------------------------------ decisions made BEFORE any model call
    def decide(self, text: str, base):
        """Fold the task state into the ordinary tool plan of this message. Returns a ToolPlan (maybe complex / resuming) or None (plain chat)."""
        from .agent import ToolPlan
        if not self.planning_enabled():
            return base
        active = self.tasks.active(self._turn_session_id)
        if active is not None and active.status == P_WAIT_USER:                    # the user answers the question the task is waiting for
            active.answers.append(_safe(text, 160))
            active.question = ""
            active.status = P_RUNNING
            self.tasks.save()
            return ToolPlan(self._cats_for(active, text), True, complex=True, resume=True, reasons=("جواب به سؤال وظیفه",))
        if self._turn_session_id in self._resume_sessions and active is not None:
            self._resume_sessions.discard(self._turn_session_id)
            return ToolPlan(self._cats_for(active, text), True, complex=True, resume=True, reasons=("ادامه‌ی وظیفه",))
        self._resume_sessions.discard(self._turn_session_id)
        self._remember_task_preference(text)
        if base is not None:
            # Exact, deterministic one-shot commands keep their Fast Path. Every
            # other tool-relevant request is classified by the model itself using
            # the goal, context and complete local tool catalog—not verb regexes.
            from .fast_commands import parse_fast_command
            if parse_fast_command(text) is None and not getattr(base, "index_only", False):
                base.complex = True
                base.reasons = ("ارزیابی معنایی هدف توسط Planner مدل",)
        return base

    def _cats_for(self, plan: TaskPlan, text: str) -> set:
        cats = set(protocol.detect_categories(text))
        for s in plan.steps:
            t = self.registry.get(s.tool) if s.tool else None
            if t:
                cats |= set(t.categories)
        return cats or (set(protocol.ALL_CATEGORIES) - {"mcp", "agents"})        # external tools join a task only when named

    def _remember_task_preference(self, text: str):
        """A standing preference about HOW to do tasks ("همیشه قبل از حذف بپرس") goes to the long-term memory as a short note. Tool results never do."""
        m = _PREF_TASK_RX.search(str(text or ""))
        if not m or "؟" in text or "?" in text or not _PREF_TASK_TOPIC.search(m.group(1)):
            return
        try:
            from .. import persona_memory
            persona_memory.add_note("ترجیح در انجام کارها: " + _safe(m.group(0), 150))
        except Exception:                                    # noqa: BLE001 - memory is a bonus
            _LOGGER.debug("Could not store the task preference in persona memory", exc_info=True)

    # ------------------------------------------------------------------ the user's commands about the task
    def handle_task_command(self, text: str, *, session_id: str | None = None):
        """Apply task controls inside the owning Session's ToolAgent state."""
        owner = self._turn_session_id if session_id is None else str(session_id or "")
        with self._use_session(owner):
            return self._handle_task_command(text, owner)

    def _handle_task_command(self, text: str, owner: str):
        """Resolve status / pause / cancel / resume / add-step / change commands."""
        if not self.planning_enabled():
            return None
        plan = self.tasks.active(owner)
        if plan is None:
            return None
        kind, payload = parse_control(text)
        if kind is None or (plan.status == P_WAIT_USER and kind == "change"):
            return None
        if kind == "status":
            return plan.report()
        if kind == "pause":
            if plan.status in (P_RUNNING, P_WAIT_CONFIRM):
                plan.status = P_PAUSED
                self.tasks.save()
            return "باشه، وظیفه متوقف شد و وضعیتش نگه داشته شد. برای ادامه «ادامه بده» بنویس."
        if kind == "cancel":
            self._cancel_task(plan)
            return "وظیفه لغو شد. هیچ مرحله‌ی دیگری اجرا نمی‌شود (کارهایی که تا الان انجام شده بود برنمی‌گردند)."
        if kind == "add_step":
            if not payload:
                return None
            st = Step(plan.next_id(), _safe(payload, 140))
            plan.steps.append(st)
            plan.updated = time.time()
            self.tasks.save()
            return f"مرحله‌ی {st.id} اضافه شد: «{st.title}». برای اجرا «ادامه بده» بنویس."
        if kind == "resume":
            if plan.status == P_WAIT_CONFIRM and self.has_pending(owner):
                return "اول باید به درخواست تأییدِ قبلی جواب بدهی: «تأیید» یا «لغو»."
            self._prepare_resume(plan)
            self._resume_sessions.add(owner)
            return None
        if kind == "change":
            plan.user_updates.append(_safe(payload, 200))
            self._prepare_resume(plan)
            self._resume_sessions.add(owner)
            return None
        return None

    def is_task_running(self, session_id: str | None = None) -> bool:
        """Return whether a task is currently executing for the requested character session."""
        owner = self._turn_session_id if session_id is None else str(session_id)
        return owner in self._running_plan_sessions

    def control_running(self, text: str, *, session_id: str | None = None):
        """While a task is being executed (the GUI is busy): a few short commands act at once, between two steps. Returns a text for the user or None
        (then the message waits in the queue as usual)."""
        owner = self._turn_session_id if session_id is None else str(session_id)
        if owner not in self._running_plan_sessions:
            return None
        plan = self.tasks.active(owner)
        if plan is None:
            return None
        kind, payload = parse_control(text)
        if kind == "status":
            return plan.report()
        if kind == "pause":
            self._pause_requests.add(owner)
            return "باشه، بعد از مرحله‌ی جاری وظیفه را متوقف می‌کنم."
        if kind == "cancel":
            self._cancel_plan_requests.add(owner)
            return "وظیفه لغو می‌شود؛ مرحله‌ای که همین الان در حال اجراست تمام می‌شود و بقیه اجرا نمی‌شوند."
        if kind == "add_step" and payload:
            plan.steps.append(Step(plan.next_id(), _safe(payload, 140)))
            self.tasks.save()
            return f"مرحله‌ی جدید اضافه شد: «{_safe(payload, 80)}». بعد از مرحله‌ی جاری در برنامه می‌آید."
        if kind == "change":
            plan.user_updates.append(_safe(payload, 200))
            self.tasks.save()
            return "دستور جدیدت را ثبت کردم؛ در مرحله‌ی بعد برنامه را با آن تطبیق می‌دهم."
        return None

    def _cancel_task(self, plan: TaskPlan):
        plan.status = P_CANCELLED
        plan.question = ""
        for s in plan.steps:
            if s.status in (AWAITING, RUNNING):
                s.status = PENDING
        pending = self._pending_by_session.get(self._turn_session_id)
        if pending is not None and getattr(pending, "plan_id", "") == plan.id:
            self._pending_by_session.pop(self._turn_session_id, None)
            self._pending_new_sessions.discard(self._turn_session_id)
        plan.updated = time.time()
        self.tasks.save()

    def _prepare_resume(self, plan: TaskPlan):
        """'ادامه بده': open steps run again; steps that failed get ONE more chance (counters reset), except those the user declined."""
        for s in plan.steps:
            if s.declined:
                continue
            if s.status in (FAILED, UNMET, RUNNING, AWAITING):
                s.status, s.attempts, s.error = PENDING, 0, ""
        plan.fail_sigs = {}
        plan.status = P_RUNNING
        plan.question = ""
        plan.updated = time.time()
        self.tasks.save()

    # ------------------------------------------------------------------ confirmation of a sensitive step that belongs to a task
    def _after_confirm(self, pending, res: ToolResult, confirmed: bool) -> str:
        plan = self.tasks.get(
            getattr(pending, "plan_id", ""),
            session_id=getattr(pending, "session_id", self._turn_session_id),
        ) if getattr(pending, "plan_id", "") else None
        if plan is None:
            return ""
        st = plan.step(pending.step_id)
        if st is None:
            return ""
        if not confirmed:
            st.status, st.declined, st.error = FAILED, True, "کاربر انجامش را لغو کرد"
            plan.status = P_PAUSED
        elif res.ok:
            tool = self.registry.get(res.tool)
            st.result = summarize_result(res.tool, res.status, res.text)
            st.data = clip(res.text, 1500)
            plan.goal_reviewed, plan.goal_verified, plan.goal_review_reason = False, False, ""
            if tool is not None and tool.verifies_result:
                st.status, st.verified = DONE, "ok"
                plan.done_sigs[call_sig(res.tool, res.args)] = st.result
            else:
                st.status, st.verified = REVIEW, ""
                plan.done_sigs[call_sig(res.tool, res.args)] = "عملیات اجرا شد؛ ارزیابی هدف در ادامه لازم است."
        else:
            st.status, st.error = FAILED, clip(res.text, 200)
            plan.fail_sigs[call_sig(res.tool, res.args)] = 1
        left = [s for s in plan.steps if s.tool and s.status in (PENDING, UNMET, RUNNING, REVIEW)]
        failed = [s for s in plan.steps if s.status == FAILED]
        goal_pending = bool(plan.success_criteria and res.ok and not plan.goal_verified)
        if confirmed and res.ok and not left and not failed and not goal_pending:
            for s in plan.steps:
                if not s.tool and s.status == PENDING:
                    s.status, s.result = DONE, "گزارش نهایی"
            plan.status = P_DONE
            suffix = ""
        else:
            plan.status = P_PAUSED if (left or goal_pending or not confirmed) else P_FAILED
            if any(s.status == REVIEW for s in plan.steps):
                suffix = "\n\nعملیات اجرا شد اما نتیجه هنوز از نظر تحقق هدف ارزیابی نشده است؛ برای بررسی وضعیت و ادامه‌ی وظیفه «ادامه بده» بنویس."
            elif goal_pending:
                suffix = "\n\nعملیات تأیید شد، اما معیارهای نهایی کار هنوز بررسی نشده‌اند؛ برای بررسی وضعیت فعلی «ادامه بده» بنویس."
            else:
                suffix = f"\n\n📋 وظیفه هنوز تمام نشده است ({'، '.join(str(s.id) for s in left) or 'بدون مرحله‌ی باقی‌مانده'}). برای ادامه «ادامه بده»، برای انصراف «لغو کار» را بنویس." if left or failed else ""
        plan.updated = time.time()
        self.tasks.save()
        return suffix

    # ------------------------------------------------------------------ one model call (shared by every phase)
    def _call(self, router, cur, prompt, temp, retry_index, on_event, emit):
        gate = planner.AgentGate(emit)
        try:
            res = router.chat_stream(cur, prompt, temp, on_chunk=gate.feed, on_event=on_event, retry_index=retry_index)
        finally:
            gate.finish()
        return res, gate

    def _poll(self, tp: TaskPlan):
        owner = tp.session_id
        if owner in self._cancel_plan_requests:
            return "cancel"
        if owner in self._pause_requests:
            return "pause"
        return None

    # ------------------------------------------------------------------ the planned turn
    def run_planned(self, router, messages, system_prompt, temperature, plan, retry_index=0, on_chunk=None, on_event=None, on_tool=None):
        emit = on_chunk or (lambda s: None)
        temp = self.temperature(temperature)
        max_steps, max_replans = self.max_steps(), self.max_replans()
        executed: list[ToolResult] = []
        owner = self._turn_session_id
        self._running_plan_sessions.add(owner)
        try:
            tp = None
            if plan.resume:
                tp = self.tasks.active(owner)
            elif retry_index and self._turn_plan_ids.get(owner):
                tp = self.tasks.get(self._turn_plan_ids[owner], session_id=owner)
            initial = None
            cur = list(messages)
            if tp is None:
                stage = self._planning_stage(router, cur, system_prompt, temp, plan, retry_index, on_event, emit, on_tool, max_steps)
                if stage[0] == "done":                         # answered directly / asked a question / stopped / plan unusable and simple loop already ran
                    return stage[1]
                _, tp, initial = stage
            else:
                self._turn_plan_ids[self._turn_session_id] = tp.id
                tp.status = P_RUNNING
                self.tasks.save()
                if on_tool:
                    on_tool({"phase": "plan_ready", "n": len(tp.steps), "estimate": tp.estimate_text(), "resumed": True})
            return self._execute_loop(router, cur, system_prompt, temp, plan, tp, initial, retry_index, on_event, emit, on_tool, executed, max_steps, max_replans)
        finally:
            self._running_plan_sessions.discard(owner)
            self.tasks.save()

    # ---- phase 1: planning (only for a NEW task)
    def _planning_stage(self, router, cur, system_prompt, temp, plan, retry_index, on_event, emit, on_tool, max_steps):
        prev = self.tasks.active(self._turn_session_id)
        previous = prev.render_state(900) if prev is not None else ""
        attempts = 0
        while True:
            prompt = system_prompt + "\n\n" + self.tools_block(plan) + "\n\n" + planner.plan_prompt(max_steps, previous)
            res, gate = self._call(router, cur, prompt, temp, retry_index, on_event, emit)
            if res.get("stopped") or self._cancel.is_set():
                return "done", self._final(res, gate.visible, [], stopped=True)
            if gate.is_plan and res.get("interrupted"):
                text = "ارتباط با مدل وسط برنامه‌ریزی قطع شد؛ هیچ مرحله‌ای اجرا نشد."
                emit(text)
                return "done", self._final(res, text, [])
            if gate.is_plan:
                try:
                    draft = planner.parse_plan(gate.raw, self.registry, max_steps)
                except ValueError as exc:
                    attempts += 1
                    if attempts >= 2:
                        # Never fall back to an unreviewed tool path after planning failed.
                        text = "نتوانستم برنامه‌ی معتبر و قابل‌ارزیابی بسازم؛ برای جلوگیری از اجرای نادرست، هیچ مرحله‌ای اجرا نشد."
                        emit(text)
                        return "done", self._final(res, text, [])
                    cur = cur + [{"role": "assistant", "content": "(برنامه)"},
                                 {"role": "user", "content": f"[System note, not from the user: your plan was rejected: {exc}. Send ONE corrected <kira_plan> block, or answer without a plan.]"}]
                    continue
                tp = self.tasks.new(self._goal_of(cur), session_id=self._turn_session_id)
                tp.apply_draft(draft)
                if not tp.goal or tp.goal == "…":
                    tp.goal = _safe(self._goal_of(cur), 240)
                if tp.steps and not tp.success_criteria and tp.goal:
                    tp.success_criteria = [tp.goal]
                for step in tp.tool_steps():
                    if not step.postcondition:
                        step.postcondition = "; ".join(tp.success_criteria) if tp.success_criteria else tp.goal
                if prev is not None and prev is not tp:
                    prev.status = P_SUPERSEDED
                self._turn_plan_ids[self._turn_session_id] = tp.id
                if draft["ask"] or (draft["missing"] and not draft["steps"]):
                    tp.status = P_WAIT_USER
                    text = tp.question or ("برای ادامه لازمه این را بدانم: " + "؛ ".join(tp.missing))
                    tp.question = tp.question or text
                    self.tasks.save()
                    emit(text)
                    return "done", self._final(res, text, [])
                tp.status = P_RUNNING
                self.tasks.save()
                if on_tool:
                    on_tool({"phase": "plan_ready", "n": len(tp.steps), "estimate": tp.estimate_text()})
                return "go", tp, None
            if gate.is_tool:                                # the model went straight to a tool: still tracked as a task (ad-hoc steps)
                tp = self.tasks.new(self._goal_of(cur), session_id=self._turn_session_id)
                tp.success_criteria = [_safe(self._goal_of(cur), 240)]
                if prev is not None and prev is not tp:
                    prev.status = P_SUPERSEDED
                tp.status = P_RUNNING
                self._turn_plan_ids[self._turn_session_id] = tp.id
                return "go", tp, (res, gate)
            return "done", self._final(res, gate.visible, [])          # a direct answer: nothing to plan

    @staticmethod
    def _goal_of(messages) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))[:240] or "…"
        return "…"

    # ---- phase 2: step-by-step execution
    def _execute_loop(self, router, cur, system_prompt, temp, plan, tp, initial, retry_index, on_event, emit, on_tool, executed, max_steps, max_replans):
        cap = max_steps * 3 + max_replans + 3              # planning + one tool round + one evidence-review round per step
        call_cap = max_steps * 2 + 2                        # hard limit of tool executions for the whole task
        halted, rnd, last_res = False, 0, {}
        while True:
            ctl = self._poll(tp)
            if ctl:
                tp.status = P_CANCELLED if ctl == "cancel" else P_PAUSED
                self._pause_requests.discard(tp.session_id)
                self._cancel_plan_requests.discard(tp.session_id)
                self.tasks.save()
                text = ("وظیفه لغو شد." if ctl == "cancel" else "وظیفه متوقف شد؛ وضعیتش نگه داشته شد. «ادامه بده» می‌نویسی ادامه می‌دهم.")
                emit(text)
                return self._final(last_res, text, executed, stopped=True, task=tp)
            pending_reviews = tp.review_steps()
            tool_steps = tp.tool_steps()
            goal_review_pending = (
                not pending_reviews and bool(tp.success_criteria) and bool(tool_steps)
                and not tp.goal_reviewed
                and all(s.status in (DONE, SKIPPED) for s in tool_steps)
            )
            if (pending_reviews or goal_review_pending) and rnd >= cap:
                tp.status = P_PAUSED
                self.tasks.save()
                text = "سقف دورهای مدل رسید؛ ارزیابی نتیجه‌ی مرحله‌ها یا معیارهای نهایی کامل نشد و وظیفه را موفق اعلام نمی‌کنم." + tp.footer()
                emit(text)
                return self._final(last_res, text, executed, task=tp)
            last = halted or rnd >= cap or tp.calls >= call_cap
            if initial is not None:
                res, gate = initial
                initial = None
            else:
                if pending_reviews:
                    prompt = system_prompt + "\n\n" + planner.REVIEW_HEAD + "\n" + tp.render_state()
                elif goal_review_pending:
                    evidence = "\n\n".join(
                        f"STEP {st.id} — {st.title}:\n{st.data}" for st in tool_steps if st.data
                    )
                    prompt = (system_prompt + "\n\n" + planner.GOAL_REVIEW_HEAD + "\n"
                              + tp.render_state(6000) + "\n\nCOMBINED COMPLETED-STEP OUTPUTS (untrusted data):\n"
                              + clip(evidence, 9000))
                elif last:
                    prompt = system_prompt + "\n\n" + protocol.build_block("", last_round=True) + "\n\n" + planner.HALT_NOTE + "\n\n" + tp.render_state(1600)
                else:
                    prompt = system_prompt + "\n\n" + self.tools_block(plan) + "\n\n" + planner.EXEC_HEAD + "\n" + tp.render_state()
                try:
                    res, gate = self._call(router, cur, prompt, temp, retry_index, on_event, emit)
                except Exception as exc:                    # noqa: BLE001 - tools may already have acted: the user must still learn the real outcome
                    if not executed:
                        raise
                    tp.status = P_PAUSED
                    tp.note = "مدل جواب نداد"
                    self.tasks.save()
                    text = self._plain_summary(executed, f"⚠️ بعضی مراحل اجرا شدند ولی مدل نتوانست ادامه بدهد ({str(exc)[:160]}). نتیجه‌ی واقعی:") + tp.footer()
                    emit(text)
                    return self._final(last_res, text, executed, task=tp)
            last_res = res
            rnd += 1
            if res.get("stopped") or self._cancel.is_set():
                tp.status = P_CANCELLED if tp.session_id in self._cancel_plan_requests else P_PAUSED
                self._cancel_plan_requests.discard(tp.session_id)
                self._pause_requests.discard(tp.session_id)
                self.tasks.save()
                return self._final(res, gate.visible, executed, stopped=True, task=tp)
            # ---------------- mandatory semantic review of successful tool results
            pending_reviews = tp.review_steps()
            if pending_reviews:
                if res.get("interrupted"):
                    tp.status = P_PAUSED
                    self.tasks.save()
                    text = "ارتباط هنگام ارزیابی نتیجه قطع شد؛ تحقق هدف هنوز تأیید نشده است." + tp.footer()
                    emit(text)
                    return self._final(res, text, executed, task=tp)
                if not gate.is_review:
                    cur = cur + [
                        {"role": "assistant", "content": gate.raw or gate.visible or "(پاسخ نامعتبر در مرحله‌ی ارزیابی)"},
                        {"role": "user", "content": "[System note: a tool result is awaiting semantic review. Your last response was not a valid <kira_review> block, so no step changed state and no tool ran. Return the required evidence review for every [review] step.]"},
                    ]
                    continue
                try:
                    reviews = planner.parse_review(gate.raw, pending_reviews)
                except ValueError as exc:
                    cur = cur + [
                        {"role": "assistant", "content": "(ارزیابی نتیجه)"},
                        {"role": "user", "content": f"[System note: review rejected: {exc}. Re-evaluate every pending step and return one valid <kira_review> block. No tool has run.]"},
                    ]
                    continue
                for item in reviews:
                    st = tp.step(item["step"])
                    if st is None:
                        continue
                    sig = call_sig(st.tool, st.args)
                    if item["verdict"] == "satisfied":
                        st.status, st.verified, st.error = DONE, "model", ""
                        st.result = summarize_result(st.tool, OK, st.data) or item["reason"]
                        tp.done_sigs[sig] = st.result
                        tool = self.registry.get(st.tool)
                        if tool is not None:
                            self._memoize(ToolResult(st.tool, OK, st.data, dict(st.args), tool.level))
                    else:
                        st.status = UNMET if st.attempts < STEP_MAX_ATTEMPTS else FAILED
                        st.verified = "uncertain" if item["verdict"] == "uncertain" else ""
                        st.error = item["reason"] or "شواهد خروجی برای اثبات تحقق هدف کافی نیست."
                        # The operation already ran successfully; never blindly repeat
                        # the same call. The model must observe state or choose another route.
                        tool = self.registry.get(st.tool)
                        if tool is not None and tool.level > READ:
                            tp.done_sigs[sig] = "عملیات اجرا شد؛ هدف با شواهد موجود تأیید نشد؛ همان فراخوانی تکرار نشود."
                tp.status = P_RUNNING
                self.tasks.save()
                cur = cur + [
                    {"role": "assistant", "content": gate.raw},
                    {"role": "user", "content": "[System note: evidence review accepted and stored in TASK STATE. Now choose the next unmet step, observe the current state, revise the remaining plan, ask one necessary question, or give the final answer only when the user's goal is actually met.]"},
                ]
                continue
            if goal_review_pending:
                if res.get("interrupted"):
                    tp.status = P_PAUSED
                    self.tasks.save()
                    text = "ارتباط هنگام بررسی معیارهای نهایی قطع شد؛ وظیفه کامل تأیید نشده است." + tp.footer()
                    emit(text)
                    return self._final(res, text, executed, task=tp)
                if not gate.is_review:
                    cur = cur + [
                        {"role": "assistant", "content": gate.raw or gate.visible or "(پاسخ نامعتبر در ارزیابی نهایی)"},
                        {"role": "user", "content": "[System note: final success criteria are awaiting review. Return one <kira_review> block for step 0 only. No tool ran.]"},
                    ]
                    continue
                goal_evidence = "\n\n".join(
                    f"STEP {st.id} — {st.title}:\n{st.data}" for st in tool_steps if st.data
                )
                goal_step = Step(0, "ارزیابی معیارهای موفقیت نهایی",
                                 postcondition="\n".join(tp.success_criteria))
                goal_step.data = clip(goal_evidence, 9000)
                try:
                    review = planner.parse_review(gate.raw, [goal_step])[0]
                except ValueError as exc:
                    cur = cur + [
                        {"role": "assistant", "content": "(ارزیابی موفقیت نهایی)"},
                        {"role": "user", "content": f"[System note: final goal review rejected: {exc}. Return one corrected <kira_review> for step 0. No tool ran.]"},
                    ]
                    continue
                tp.goal_reviewed = True
                tp.goal_verified = review["verdict"] == "satisfied"
                tp.goal_review_reason = "" if tp.goal_verified else review["reason"]
                tp.status = P_RUNNING
                self.tasks.save()
                note = ("[System note: every final success criterion was supported by exact output evidence. You may now give the final answer based only on verified results.]"
                        if tp.goal_verified else
                        "[System note: the final success criteria are NOT all proven. Add observation/action steps with a revised <kira_plan>, ask one necessary question, or report that the goal could not be completed. Do not claim success.]")
                cur = cur + [
                    {"role": "assistant", "content": gate.raw},
                    {"role": "user", "content": note},
                ]
                continue
            if gate.is_review:
                cur = cur + [
                    {"role": "assistant", "content": gate.raw},
                    {"role": "user", "content": "[System note: no step is awaiting review. Continue with the next planned action or final answer.]"},
                ]
                continue
            # ---------------- a tool request
            if gate.is_tool:
                if res.get("interrupted"):
                    text = "ارتباط با مدل وسط درخواست ابزار قطع شد؛ این مرحله اجرا نشد." + tp.footer()
                    tp.status = P_PAUSED
                    emit(text)
                    return self._final(res, text, executed, task=tp)
                calls, errors = protocol.parse_calls(gate.raw)
                if last or not (calls or errors):
                    text = (self._plain_summary(executed, "نتوانستم به جواب نهایی برسم.") if executed else "درخواست ابزار قابل اجرا نبود و چیزی اجرا نشد.") + tp.footer()
                    tp.status = P_PAUSED
                    emit(text)
                    return self._final(res, text, executed, task=tp)
                results, notes = self._run_calls_planned(tp, calls, errors, on_tool, call_cap)
                executed.extend(results)
                self.tasks.save()
                if self._cancel.is_set():
                    tp.status = P_CANCELLED if tp.session_id in self._cancel_plan_requests else P_PAUSED
                    self._cancel_plan_requests.discard(tp.session_id)
                    self._pause_requests.discard(tp.session_id)
                    self.tasks.save()
                    return self._final(res, "", executed, stopped=True, task=tp)
                if any(r.status == NEEDS_CONFIRM for r in results):
                    halted = True                           # nothing else may run before the user answers
                cur = cur + [{"role": "assistant", "content": "\n".join(protocol.canonical_call(c) for c in calls) or "(درخواست ابزار)"},
                             {"role": "user", "content": self._results_message_planned(results, notes)}]
                continue
            # ---------------- a plan revision or a question
            if gate.is_plan:
                if res.get("interrupted"):
                    text = "ارتباط با مدل وسط اصلاح برنامه قطع شد." + tp.footer()
                    emit(text)
                    return self._final(res, text, executed, task=tp)
                try:
                    draft = planner.parse_plan(gate.raw, self.registry, max_steps, revise=True)
                except ValueError as exc:
                    cur = cur + [{"role": "assistant", "content": "(برنامه)"},
                                 {"role": "user", "content": f"[System note, not from the user: that plan block was rejected: {exc}. Continue with a tool block, a corrected revision or the final answer.]"}]
                    continue
                if draft["ask"]:
                    tp.question, tp.status = draft["ask"], P_WAIT_USER
                    self.tasks.save()
                    emit(draft["ask"])
                    return self._final(res, draft["ask"], executed, task=tp)
                if tp.revisions >= max_replans:
                    halted = True
                    cur = cur + [{"role": "assistant", "content": "(برنامه)"},
                                 {"role": "user", "content": "[System note, not from the user: the replanning limit is reached. Do not change the plan again: report honestly what was done and what was not.]"}]
                    continue
                tp.apply_draft(draft, revise=True)
                tp.user_updates = []
                self.tasks.save()
                if on_tool:
                    on_tool({"phase": "plan_ready", "n": len(tp.steps), "estimate": tp.estimate_text(), "revised": True})
                cur = cur + [{"role": "assistant", "content": "(برنامه اصلاح شد)"},
                             {"role": "user", "content": "[System note, not from the user: the plan was revised; see TASK STATE. Continue with the next step.]"}]
                continue
            # ---------------- the final answer
            text = gate.visible
            self._settle_plan(tp)
            footer = tp.footer()
            if self.has_new_pending_confirmation(tp.session_id) and not re.search(r"تأیید|تایید|confirm", text + footer):
                footer += "\n\n(برای انجام همین کار «تأیید» بنویس؛ برای انصراف «لغو».)"
            if footer:
                emit(footer)
                text += footer
            self.tasks.save()
            return self._final(res, text, executed, task=tp)

    def _settle_plan(self, tp: TaskPlan):
        """Status of the task when the model gives its final answer. A thinking step is done only if every tool step is."""
        tool_steps = tp.tool_steps()
        all_ok = all(s.status in (DONE, SKIPPED) for s in tool_steps)
        if all_ok:
            for s in tp.steps:
                if not s.tool and s.status in (PENDING, RUNNING):
                    s.status, s.result = DONE, "گزارش/جمع‌بندی ارائه شد"
        pending = self._pending_by_session.get(tp.session_id)
        if any(s.status == AWAITING for s in tp.steps) or (
            pending is not None and getattr(pending, "plan_id", "") == tp.id
        ):
            tp.status = P_WAIT_CONFIRM
        elif any(s.status in (FAILED, UNMET) for s in tp.steps):
            tp.status = P_FAILED
        elif tp.success_criteria and tool_steps and not tp.goal_verified:
            tp.status = P_FAILED if tp.goal_reviewed else P_PAUSED
        elif all(s.status in (DONE, SKIPPED) for s in tp.steps):
            tp.status = P_DONE
            tp.interrupted = False
        else:
            tp.status = P_PAUSED
        tp.updated = time.time()

    # ---- running the calls of one round
    def _run_calls_planned(self, tp: TaskPlan, calls, errors, on_tool, call_cap):
        from .agent import TOOL_LABELS, Pending
        results = [ToolResult("?", BAD_ARGS, msg) for msg in errors]
        notes: list[str] = []
        total = max(len(tp.steps), 1)
        awaiting_confirmation = self.has_pending(self._turn_session_id)
        for call in calls[:protocol.MAX_CALLS_PER_ROUND]:
            if self._cancel.is_set():
                break
            name, args = call["tool"], call.get("args") or {}
            tool = self.registry.get(name)
            label = TOOL_LABELS.get(name, name)
            sig = call_sig(name, args)
            if tool is None:
                results.append(self.registry.execute(name, args))             # unknown tool: the registry explains
                notes.append(f"unknown tool '{name}'")
                continue
            st = tp.bind(name, call.get("step"), label, tool.level >= SENSITIVE)
            if awaiting_confirmation:
                # A Session has one confirmation slot. Keep later plan steps
                # pending instead of replacing the operation the user saw.
                results.append(ToolResult(
                    name,
                    DENIED,
                    "این مرحله اجرا نشد؛ مرحله‌ی قبلی منتظر تأیید صریح کاربر است. "
                    "پس از تعیین تکلیف آن، وظیفه را ادامه بده.",
                    args if isinstance(args, dict) else {},
                    tool.level,
                ))
                notes.append(f"step {st.id}: not run because an earlier step awaits confirmation")
                continue
            waiting = tp.deps_unmet(st)
            if waiting:
                results.append(ToolResult(name, BAD_ARGS, f"مرحله‌ی {st.id} هنوز نمی‌تواند اجرا شود: اول مرحله‌ی {', '.join(map(str, waiting))} باید تمام شود.", args, tool.level))
                notes.append(f"step {st.id}: blocked by unfinished dependency {waiting}")
                continue
            if sig in tp.done_sigs:
                results.append(ToolResult(name, OK, f"[این عملیات قبلاً با موفقیت انجام شده ({tp.done_sigs[sig]}) و دوباره اجرا نشد.]", args, tool.level, cached=True))
                notes.append(f"step {st.id}: already done, not repeated")
                continue
            if tp.fail_sigs.get(sig, 0) >= FAIL_SIG_MAX:
                results.append(ToolResult(name, BAD_ARGS, "این فراخوانی با همین آرگومان‌ها دو بار شکست خورد و دوباره اجرا نمی‌شود. مسیر دیگری انتخاب کن، برنامه را اصلاح کن یا از کاربر بپرس.", args, tool.level))
                notes.append(f"step {st.id}: the same call already failed twice")
                continue
            if tp.calls >= call_cap:
                results.append(ToolResult(name, BAD_ARGS, "سقف تعداد اجرای ابزار در این وظیفه رسید؛ دیگر چیزی اجرا نمی‌شود.", args, tool.level))
                notes.append("tool-call limit of the task reached")
                continue
            tp.calls += 1
            st.status, st.args = RUNNING, dict(args)
            if on_tool:
                on_tool({"phase": "plan_step", "i": min(st.id, total) if st.id <= total else total, "n": total, "title": st.title})
                on_tool({"phase": "tool_start", "tool": name, "label": label})
            res = self.registry.execute(name, args)
            st.attempts += 1
            if res.status == ERROR and tool.level == READ and classify_error(res.status, res.text) == "transient" and st.attempts < STEP_MAX_ATTEMPTS:
                time.sleep(0.8)                                              # a temporary error of a READ-ONLY tool: one more try, never for actions
                res = self.registry.execute(name, args)
                st.attempts += 1
            if on_tool:
                on_tool({"phase": "tool_done", "tool": name, "label": label, "status": res.status, "ms": res.ms})
            results.append(res)
            notes.append(self._settle_step(tp, st, res, sig, Pending))
            if res.status == NEEDS_CONFIRM:
                awaiting_confirmation = True
        return results, notes

    def _settle_step(self, tp, st, res: ToolResult, sig: str, Pending) -> str:
        """Update the step from the REAL result and return the verification sentence for the model."""
        if res.status == NEEDS_CONFIRM:
            st.status, st.result = AWAITING, "منتظر تأیید کاربر"
            self._pending_by_session[self._turn_session_id] = Pending(
                res.tool, dict(res.args), res.summary,
                step_id=st.id, plan_id=tp.id, session_id=self._turn_session_id,
            )
            self._pending_new_sessions.add(self._turn_session_id)
            tp.status = P_WAIT_CONFIRM
            return f"step {st.id}: waiting for the USER's confirmation; nothing was changed; tell the user exactly what will happen and ask for «تأیید» / «لغو». Do not continue the plan."
        if res.status == OK:
            st.status, st.error, st.verified = REVIEW, "", ""
            st.data = clip(res.text, 1500)
            tp.goal_reviewed, tp.goal_verified, tp.goal_review_reason = False, False, ""
            st.result = summarize_result(res.tool, res.status, res.text)
            # Record execution to suppress duplicate side effects while the model
            # checks whether the user's intended postcondition actually holds.
            # Never blindly repeat an action while its result is under review.
            # Read-only observations may safely be repeated to verify fresh state.
            if res.level > READ:
                tp.done_sigs[sig] = "ابزار اجرا شد؛ ارزیابی تحقق هدف هنوز انجام نشده است."
            return (f"step {st.id}: tool execution returned OK, but goal completion is NOT established. "
                    "The step is awaiting semantic evidence review; do not call the same operation again.")
        kind = classify_error(res.status, res.text)
        st.error = clip(res.text, 200)
        tp.fail_sigs[sig] = tp.fail_sigs.get(sig, 0) + 1
        if kind == "transient" and st.attempts < STEP_MAX_ATTEMPTS:
            st.status = PENDING
            return f"step {st.id}: temporary error ({res.status}). You may try this step once more."
        st.status = FAILED
        hint = {"missing": "the target does not exist: look for the real path first or ask the user",
                "permanent": "this cannot be fixed by repeating it: choose another route, revise the plan or tell the user"}.get(kind, "")
        return f"step {st.id}: FAILED ({res.status}). {hint}."

    @staticmethod
    def _results_message_planned(results, notes) -> str:
        blocks = [protocol.result_block(r.tool, r.status, r.text) for r in results]
        verdict = "\n".join(f"- {n}" for n in notes) if notes else ""
        return "\n\n".join(blocks) + ("\n\nSYSTEM VERIFICATION:\n" + verdict if verdict else "") + "\n\n" + planner.RESULTS_NOTE
