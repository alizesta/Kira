"""Task Plan, task state, result verification and error classification for Kira's autonomous agent.

Everything here is plain, deterministic code (no model call, no Provider knowledge):

* ``TaskPlan`` / ``Step``   the internal plan of one multi-step request: goal, steps, status of every step, results, errors.
* ``TaskStore``             saves the plan to ``kira_tasks.json`` so an unfinished task survives closing the program. Only short,
                            redacted summaries are written: never file contents, never keys, never the full results of tools.
* ``verify``                conservative status/empty-output checks only; semantic postconditions are judged by the model.
* ``classify_error``        transient (retry once, read-only tools only) vs permanent vs needs-confirmation.
* ``parse_control``         the user's own commands during a task (status / pause / cancel / resume / add a step / change the goal).

The plan state is rendered into the prompt on every round (``render_state``), so a switch of Route / Provider in the middle of a
task loses nothing: the state lives here, not inside any model's conversation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

from .registry import redact_secrets, clip, OK, ERROR, DENIED, NEEDS_CONFIRM, BAD_ARGS, UNKNOWN

_LOGGER = logging.getLogger(__name__)

FILE_NAME = "kira_tasks.json"
HISTORY_KEEP = 5                       # finished / cancelled plans kept besides the active one
STALE_AFTER = 24 * 3600                # an older unfinished task is still resumable but is marked as possibly outdated
STEP_MAX_ATTEMPTS = 2                  # one call may be tried this many times (a retry only for transient errors of read-only tools)
FAIL_SIG_MAX = 2                       # the same failing call (same tool + arguments) is never executed a third time

# step status
PENDING, RUNNING, REVIEW, DONE, FAILED, UNMET, SKIPPED, AWAITING = "pending", "running", "review", "done", "failed", "unmet", "skipped", "awaiting_confirm"
# plan status
P_PLANNING, P_RUNNING, P_WAIT_USER, P_WAIT_CONFIRM, P_PAUSED, P_DONE, P_FAILED, P_CANCELLED, P_SUPERSEDED = (
    "planning", "running", "waiting_user", "waiting_confirm", "paused", "done", "failed", "cancelled", "superseded")
ACTIVE = (P_PLANNING, P_RUNNING, P_WAIT_USER, P_WAIT_CONFIRM, P_PAUSED)
FINISHED = (P_DONE, P_FAILED, P_CANCELLED, P_SUPERSEDED)

_MARK = {PENDING: "⚪", RUNNING: "⏳", REVIEW: "🔎", DONE: "✅", FAILED: "❌", UNMET: "⚠️", SKIPPED: "➖", AWAITING: "⏸"}
_STATUS_FA = {P_PLANNING: "در حال برنامه‌ریزی", P_RUNNING: "در حال اجرا", P_WAIT_USER: "منتظر جواب تو", P_WAIT_CONFIRM: "منتظر تأیید تو",
              P_PAUSED: "متوقف‌شده", P_DONE: "تمام‌شده", P_FAILED: "ناقص / ناموفق", P_CANCELLED: "لغوشده", P_SUPERSEDED: "جایگزین‌شده با درخواست جدید"}
_SECONDS = {"search_files": 8, "read_file": 3, "get_resource_usage": 3, "get_network_info": 4, "open_app": 12}


def _safe(text, limit: int) -> str:
    """Short, single-line, secrets masked: the only form in which user text or tool output is ever written to disk."""
    return clip(redact_secrets(" ".join(str(text or "").split())), limit)


_PATH_RX = re.compile(r"[A-Za-z]:\\[^\s—·|\"'<>]*")


def _nopath(text, limit: int) -> str:
    """For what is written to disk: a Windows path inside a result line is replaced (the task only needs to know WHAT happened, not where)."""
    return _safe(_PATH_RX.sub("‹مسیر›", str(text or "")), limit)


def call_sig(name: str, args) -> str:
    """Identity of one tool call (tool + arguments). Only this hash is persisted, never the arguments themselves."""
    raw = name + json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------- data model
@dataclass
class Step:
    id: int
    title: str
    tool: str = ""                       # "" = a thinking / reporting step done by the model itself (sort, compare, write the report)
    depends_on: list = field(default_factory=list)
    confirm: bool = False                # the tool is sensitive: it runs only after the user's explicit confirmation
    status: str = PENDING
    args: dict = field(default_factory=dict)
    attempts: int = 0
    result: str = ""                     # one-line summary of the REAL result (persisted)
    error: str = ""
    verified: str = ""                   # "" | "ok" | "model" | "unverified" | "uncertain"
    adhoc: bool = False                  # created by the executor because the model called a tool that no step covered
    declined: bool = False               # the user answered "cancel" to the confirmation of this step: it is never re-asked on resume
    data: str = field(default="", repr=False, compare=False)       # real result text, IN MEMORY ONLY (never persisted)
    postcondition: str = ""                                         # observable condition that proves this individual step reached its goal

    def to_dict(self) -> dict:
        return {"id": self.id, "title": _safe(self.title, 140), "postcondition": _safe(self.postcondition, 240), "tool": self.tool, "depends_on": list(self.depends_on), "confirm": self.confirm,
                "status": self.status, "attempts": self.attempts, "result": _nopath(self.result, 220), "error": _nopath(self.error, 220), "verified": self.verified, "adhoc": self.adhoc, "declined": self.declined}

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(int(d.get("id", 0)), str(d.get("title", ""))[:140], str(d.get("tool", "")), [int(x) for x in d.get("depends_on", []) if str(x).lstrip("-").isdigit()],
                   bool(d.get("confirm")), str(d.get("status", PENDING)), {}, int(d.get("attempts", 0)),
                   str(d.get("result", "")), str(d.get("error", "")), str(d.get("verified", "")), bool(d.get("adhoc")), bool(d.get("declined")),
                   postcondition=str(d.get("postcondition", ""))[:240])


@dataclass
class TaskPlan:
    id: str
    goal: str
    steps: list = field(default_factory=list)
    status: str = P_PLANNING
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    assumptions: list = field(default_factory=list)      # the model's guesses: NOT facts
    missing: list = field(default_factory=list)          # information that is still unknown
    question: str = ""                                   # the one question waiting for the user
    answers: list = field(default_factory=list)          # the user's answers / updates while the task lives
    user_updates: list = field(default_factory=list)
    revisions: int = 0
    calls: int = 0
    interrupted: bool = False                            # the program was closed in the middle of this task
    note: str = ""
    done_sigs: dict = field(default_factory=dict)        # signature -> summary of a call that already SUCCEEDED (never executed again)
    fail_sigs: dict = field(default_factory=dict)        # signature -> how many times it failed
    session_id: str = ""                                  # owner character session; old records default to the legacy session
    success_criteria: list = field(default_factory=list)   # observable end-state conditions for the whole task
    goal_reviewed: bool = False                             # whether the current plan version received its final evidence review
    goal_verified: bool = False                             # true only when every final success criterion has evidence
    goal_review_reason: str = ""                            # why final criteria were not proven

    # ---------------------------------------------------------------- steps
    def step(self, sid) -> Step | None:
        if isinstance(sid, bool):
            return None
        try:
            sid = int(sid)
        except (TypeError, ValueError, OverflowError):
            return None
        if sid <= 0:
            return None
        matches = [step for step in self.steps if step.id == sid]
        # Duplicate persisted IDs make references ambiguous; fail closed.
        return matches[0] if len(matches) == 1 else None

    def next_id(self) -> int:
        return max([s.id for s in self.steps] + [0]) + 1

    def deps_unmet(self, st: Step) -> list:
        out = []
        for dependency in st.depends_on:
            # Persisted task state is untrusted: malformed, non-positive, missing,
            # or ambiguous references must never be treated as satisfied.
            if isinstance(dependency, bool):
                out.append(dependency)
                continue
            try:
                dependency_id = int(dependency)
            except (TypeError, ValueError, OverflowError):
                out.append(dependency)
                continue
            if dependency_id <= 0:
                out.append(dependency_id)
                continue
            dep = self.step(dependency_id)
            if dep is None or dep.status not in (DONE, SKIPPED):
                out.append(dependency_id)
        return out

    def next_step(self) -> Step | None:
        for s in self.steps:
            if s.status in (PENDING, UNMET) and not self.deps_unmet(s) and s.attempts < STEP_MAX_ATTEMPTS:
                return s
        return None

    def tool_steps(self) -> list:
        return [s for s in self.steps if s.tool]

    def review_steps(self) -> list:
        return [s for s in self.steps if s.tool and s.status == REVIEW]

    def counts(self) -> tuple:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status in (DONE, SKIPPED))
        return done, total

    def bind(self, tool: str, step_id, label: str, sensitive: bool) -> Step:
        """Which step does this tool call belong to? The model's own ``step`` id first, then the first open step of that tool, else a new ad-hoc step."""
        st = self.step(step_id)
        if st is not None and st.status in (DONE, SKIPPED):
            st = None
        if st is None:
            st = next((s for s in self.steps if s.tool == tool and s.status in (PENDING, UNMET, FAILED, AWAITING) and s.attempts < STEP_MAX_ATTEMPTS), None)
        if st is None:
            st = Step(self.next_id(), label, tool, adhoc=True, postcondition=self.goal)
            self.steps.append(st)
        if st.tool != tool:
            st.tool = tool                                   # the model chose another tool for this step; the registry still decides what it may do
        st.confirm = st.confirm or sensitive
        return st

    def apply_draft(self, draft: dict, *, revise: bool = False):
        """Install steps from a validated draft (see planner.parse_plan). A revision keeps every finished step and replaces the open ones."""
        keep = [s for s in self.steps if s.status in (DONE, SKIPPED)] if revise else []
        if revise:
            replaced = any(r["tool"] for r in draft["steps"])           # a failed step counts as "replaced" only if the new plan really tries another way
            for s in self.steps:
                if s.status in (FAILED, UNMET):
                    if replaced and not s.declined:
                        s.status, s.result = SKIPPED, "جایگزین شد: " + _safe(s.error or s.result, 120)
                    keep.append(s)
            keep.sort(key=lambda x: x.id)
        base = max([s.id for s in keep] + [0])
        remap, new = {}, []
        for raw in draft["steps"]:
            nid = base + len(new) + 1
            remap[raw["id"]] = nid
            deps = [remap[d] for d in raw["depends_on"] if d in remap]
            new.append(Step(nid, raw["title"], raw["tool"], sorted(set(deps)), raw["confirm"],
                             postcondition=str(raw.get("postcondition") or "")[:240]))
        self.steps = keep + new
        if draft.get("goal") and not revise:
            self.goal = _safe(draft["goal"], 240)
        if draft.get("success_criteria"):
            self.success_criteria = [" ".join(str(x).split())[:240] for x in draft["success_criteria"]][:6]
        if revise:
            self.goal_reviewed = False
            self.goal_verified = False
            self.goal_review_reason = ""
        if draft.get("assumptions"):
            self.assumptions = [_safe(a, 160) for a in draft["assumptions"]][:6]
        self.missing = [_safe(m, 160) for m in draft.get("missing", [])][:5]
        self.question = _safe(draft.get("ask", ""), 300)
        self.revisions += 1 if revise else 0
        self.updated = time.time()

    # ---------------------------------------------------------------- numbers
    def estimate_seconds(self) -> int:
        """A rough, honest estimate: ~4 s per model round plus a typical time per tool. Only the steps still open count."""
        open_tools = [s for s in self.tool_steps() if s.status in (PENDING, UNMET, RUNNING)]
        return int(4 * (len(open_tools) + 1) + sum(_SECONDS.get(s.tool, 2) for s in open_tools))

    def estimate_text(self) -> str:
        left = [s for s in self.tool_steps() if s.status in (PENDING, UNMET, RUNNING)]
        if not left:
            return ""
        sec = self.estimate_seconds()
        return f"حدود {len(left)} مرحله‌ی باقی‌مانده، تخمین تقریبی {sec if sec < 90 else round(sec / 60)} {'ثانیه' if sec < 90 else 'دقیقه'}"

    # ---------------------------------------------------------------- prompt state (re-sent every round: survives a Route change)
    def render_state(self, limit: int = 2600) -> str:
        done, total = self.counts()
        status_line = f"Status: {self.status}; {done}/{total} steps finished."
        if self.estimate_text():
            status_line += f" {self.estimate_text()}."
        lines = [
            "TASK STATE (kept by the system, not by you: it stays correct even if the model or provider changes in the middle of the task):",
            f"Goal: {self.goal}",
            status_line,
        ]
        if self.success_criteria:
            lines.append("FINAL SUCCESS CRITERIA (all must hold before the task is complete):")
            lines.extend(f"- {item}" for item in self.success_criteria)
            if self.goal_reviewed:
                state = "SATISFIED" if self.goal_verified else "NOT PROVEN"
                lines.append(f"FINAL GOAL REVIEW: {state}. {self.goal_review_reason}")
            else:
                lines.append("FINAL GOAL REVIEW: pending.")
        nxt = self.next_step()
        for s in self.steps:
            tag = "next" if s is nxt else s.status
            tool = f" ({s.tool}{', needs user confirmation' if s.confirm else ''})" if s.tool else " (thinking/report step, no tool)"
            expected = f" | postcondition: {s.postcondition}" if s.postcondition else ""
            dep = f" after {','.join(map(str, s.depends_on))}" if s.depends_on else ""
            res = f" -> {s.result}" if s.result else (f" -> ERROR: {s.error}" if s.error else "")
            lines.append(f"[{tag}] {s.id}. {s.title}{tool}{expected}{dep}{res}"[:500])
        facts = [f"{s.id}: {s.result}" + (" (completion NOT verified)" if s.verified == "unverified" else "") for s in self.steps if s.status == DONE and s.result][:8]
        lines.append("VERIFIED FACTS (summaries of real tool results; nothing else in this task is a verified fact):")
        lines += [f"- {f}" for f in facts] or ["- (none yet)"]
        temp = [f"step {s.id}: {clip(s.data, 700)}" for s in self.steps if s.status in (REVIEW, DONE) and s.data][-4:]
        if temp:
            lines.append("TEMPORARY DATA (real output of the latest steps, this session only, may be outdated):")
            lines += [f"- {t}" for t in temp]
        if self.assumptions:
            lines.append("ASSUMPTIONS made while planning (guesses, NOT facts; verify or ask if they matter):")
            lines += [f"- {a}" for a in self.assumptions]
        if self.missing or self.question:
            lines.append("OPEN QUESTIONS: " + "; ".join(self.missing + ([self.question] if self.question else [])))
        if self.answers:
            lines.append("USER ANSWERS to your questions: " + " | ".join(self.answers[-3:]))
        if self.user_updates:
            lines.append("USER UPDATES since the plan was made (follow them; revise the plan if the goal changed): " + " | ".join(self.user_updates[-3:]))
        if self.interrupted:
            lines.append("NOTE: the program was closed during this task. Steps whose data is missing above must be re-read if you need their content.")
        if time.time() - self.updated > STALE_AFTER:
            lines.append("NOTE: this task is more than a day old: re-check anything that may have changed before relying on it.")
        out = "\n".join(lines)
        return out if len(out) <= limit else out[:limit].rstrip() + "\n[state cut]"

    # ---------------------------------------------------------------- reports for the user (Persian)
    def report(self) -> str:
        done, total = self.counts()
        lines = [f"🧭 وظیفه: {self.goal}", f"وضعیت: {_STATUS_FA.get(self.status, self.status)} — {done} از {total} مرحله انجام شده."]
        for s in self.steps:
            extra = s.result or s.error
            lines.append(f"{_MARK.get(s.status, '⚪')} {s.id}. {s.title}" + (f" — {clip(extra, 110)}" if extra else ""))
        if self.question:
            lines.append(f"❓ سؤال باز: {self.question}")
        est = self.estimate_text()
        if est and self.status in (P_RUNNING, P_PAUSED):
            lines.append(est + ".")
        if self.status == P_PAUSED or self.interrupted:
            lines.append("برای ادامه بنویس «ادامه بده»؛ برای انصراف «لغو کار».")
        return "\n".join(lines)

    def footer(self) -> str:
        """Honest one-block summary appended to the final answer when the task is NOT fully and cleanly finished (never claims success)."""
        bad = [s for s in self.steps if s.status in (FAILED, UNMET)]
        open_ = [s for s in self.steps if s.tool and s.status in (PENDING, RUNNING, REVIEW, AWAITING)]
        unver = [s for s in self.steps if s.status == DONE and s.verified == "unverified"]
        tool_steps = self.tool_steps()
        goal_pending = bool(self.success_criteria and tool_steps and not self.goal_reviewed
                            and all(s.status in (DONE, SKIPPED) for s in tool_steps))
        goal_unproven = bool(self.success_criteria and self.goal_reviewed and not self.goal_verified)
        if not (bad or open_ or unver or goal_unproven or goal_pending):
            return ""
        done, total = self.counts()
        out = [f"\n\n📋 وضعیت وظیفه: {done} از {total} مرحله انجام شد."]
        for s in bad:
            out.append(f"❌ مرحله‌ی {s.id} «{s.title}» به نتیجه نرسید" + (f": {clip(s.error or s.result, 140)}" if (s.error or s.result) else "."))
        for s in open_:
            if s.status == REVIEW:
                out.append(f"🔎 مرحله‌ی {s.id} «{s.title}» اجرا شد اما نتیجه هنوز از نظر تحقق هدف ارزیابی نشده است.")
            else:
                out.append(f"⏸ مرحله‌ی {s.id} «{s.title}» انجام نشد" + (" (منتظر تأیید تو)." if s.status == AWAITING else "."))
        for s in unver:
            out.append(f"⚠️ مرحله‌ی {s.id} «{s.title}»: اجرا شد ولی نتیجه‌اش تأیید نشد.")
        if goal_pending:
            out.append("⏸ معیارهای نهایی هنوز با شواهد بررسی نشده‌اند؛ برای بررسی و ادامه «ادامه بده» بنویس.")
        if goal_unproven:
            out.append("❌ معیارهای نهایی کار با شواهد موجود تأیید نشدند؛ وظیفه کامل اعلام نمی‌شود.")
            if self.goal_review_reason:
                out.append("علت: " + clip(self.goal_review_reason, 220))
            out.append("برای بررسی دوباره یا افزودن مراحل، «ادامه بده» بنویس.")
        if any(s.status == AWAITING for s in open_):
            out.append("برای انجام مرحله‌ی در انتظار «تأیید» و برای انصراف «لغو» بنویس.")
        elif bad or open_:
            out.append("برای ادامه‌ی بقیه بنویس «ادامه بده».")
        return "\n".join(out)

    # ---------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {"id": self.id, "goal": _safe(self.goal, 240), "success_criteria": [_safe(x, 240) for x in self.success_criteria][:6],
                "goal_reviewed": self.goal_reviewed, "goal_verified": self.goal_verified, "goal_review_reason": _safe(self.goal_review_reason, 220),
                "session_id": self.session_id, "status": self.status, "created": self.created, "updated": self.updated,
                "steps": [s.to_dict() for s in self.steps], "assumptions": [_safe(a, 160) for a in self.assumptions][:6],
                "missing": [_safe(m, 160) for m in self.missing][:5], "question": _safe(self.question, 300),
                "answers": [_safe(a, 160) for a in self.answers][-4:], "user_updates": [_safe(a, 160) for a in self.user_updates][-4:],
                "revisions": self.revisions, "calls": self.calls, "interrupted": self.interrupted, "note": _safe(self.note, 200),
                "done_sigs": {k: _nopath(v, 120) for k, v in list(self.done_sigs.items())[-30:]}, "fail_sigs": dict(list(self.fail_sigs.items())[-30:])}

    @classmethod
    def from_dict(cls, d: dict) -> "TaskPlan":
        p = cls(str(d.get("id", "")), str(d.get("goal", ""))[:240])
        p.success_criteria = [" ".join(str(x).split())[:240] for x in d.get("success_criteria", []) if str(x).strip()][:6]
        p.goal_reviewed, p.goal_verified = bool(d.get("goal_reviewed")), bool(d.get("goal_verified"))
        p.goal_review_reason = _safe(d.get("goal_review_reason", ""), 220)
        p.session_id = str(d.get("session_id") or "kira")
        p.steps = [Step.from_dict(x) for x in d.get("steps", []) if isinstance(x, dict)]
        if p.steps and not p.success_criteria and p.goal:
            p.success_criteria = [p.goal]
        for step in p.steps:
            if not step.postcondition:
                step.postcondition = p.goal
        p.status = str(d.get("status", P_PAUSED))
        p.created, p.updated = float(d.get("created", time.time())), float(d.get("updated", time.time()))
        p.assumptions, p.missing = list(d.get("assumptions", [])), list(d.get("missing", []))
        p.question, p.answers, p.user_updates = str(d.get("question", "")), list(d.get("answers", [])), list(d.get("user_updates", []))
        p.revisions, p.calls, p.interrupted, p.note = int(d.get("revisions", 0)), int(d.get("calls", 0)), bool(d.get("interrupted")), str(d.get("note", ""))
        p.done_sigs, p.fail_sigs = dict(d.get("done_sigs", {})), {k: int(v) for k, v in dict(d.get("fail_sigs", {})).items()}
        return p


class TaskStore:
    """The active plan plus a few finished ones, in ``kira_tasks.json`` (memory only when no folder is given)."""

    def __init__(self, data_dir=None):
        self.path = (data_dir / FILE_NAME) if data_dir is not None else None
        self.plans: list[TaskPlan] = []
        self.lock = threading.RLock()
        self._load_failed = False
        self.load()

    def load(self):
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("plans", []), list):
                raise ValueError("task file must contain an object with a plans list")
        except Exception:                                    # noqa: BLE001 - a damaged task file must never stop Kira
            self._load_failed = True
            _LOGGER.exception("Could not load task state from %s; original file will be preserved", self.path)
            return

        plans = []
        malformed = False
        for index, item in enumerate(raw.get("plans", [])):
            if not isinstance(item, dict):
                malformed = True
                _LOGGER.warning("Ignoring malformed task record %s in %s", index, self.path)
                continue
            try:
                plans.append(TaskPlan.from_dict(item))
            except Exception:                                # noqa: BLE001 - retain other valid tasks
                malformed = True
                _LOGGER.exception("Ignoring malformed task record %s in %s", index, self.path)
        if malformed:
            self._load_failed = True
            _LOGGER.error("Some task records in %s were unreadable; original file will be preserved", self.path)
        for p in plans:
            if p.status in (P_RUNNING, P_PLANNING):          # the program was closed while this task was running
                p.status, p.interrupted = P_PAUSED, True
                for s in p.steps:
                    if s.status in (RUNNING, AWAITING):
                        s.status = PENDING
            elif p.status == P_WAIT_CONFIRM:                 # a confirmation is never kept across a restart: the user must be asked again
                p.status, p.interrupted = P_PAUSED, True
                for s in p.steps:
                    if s.status == AWAITING:
                        s.status = PENDING
            for s in p.steps:
                if s.status == REVIEW:
                    # Full tool output is intentionally memory-only. Re-observe after restart;
                    # never blindly repeat an action whose result has not been reviewed.
                    s.status = UNMET
                    s.verified = "uncertain"
                    s.error = "نتیجه‌ی کامل ابزار پس از راه‌اندازی در دسترس نیست؛ پیش از تکرار عملیات، وضعیت فعلی را دوباره مشاهده کن."
            if p.status in ACTIVE and p.goal_verified:
                # Goal evidence is memory-only. A persisted boolean is not proof after restart.
                p.goal_reviewed, p.goal_verified = False, False
                p.goal_review_reason = "شواهد نهایی پس از راه‌اندازی در حافظه باقی نمانده‌اند؛ وضعیت فعلی باید دوباره مشاهده شود."
        self.plans = self._trim_history(plans)

    @staticmethod
    def _trim_history(plans: list[TaskPlan]) -> list[TaskPlan]:
        """Keep five completed plans plus every active plan per character Session."""
        now = time.time()
        grouped: dict[str, list[TaskPlan]] = {}
        for plan in plans:
            grouped.setdefault(str(plan.session_id or ""), []).append(plan)

        retained_ids: set[int] = set()
        for records in grouped.values():
            active = [
                plan for plan in records
                if plan.status in ACTIVE
                or (plan.status == P_FAILED and now - plan.updated <= STALE_AFTER)
            ]
            active_ids = {id(plan) for plan in active}
            completed = [plan for plan in records if id(plan) not in active_ids]
            retained_ids.update(active_ids)
            retained_ids.update(id(plan) for plan in completed[-HISTORY_KEEP:])

        # Preserve original cross-character chronology when writing the shared file.
        return [plan for plan in plans if id(plan) in retained_ids]

    def save(self):
        if self.path is None:
            return True
        with self.lock:
            if self._load_failed:
                _LOGGER.error("Refusing to overwrite unreadable task state at %s; current task changes remain memory-only", self.path)
                return False
            self.plans = self._trim_history(self.plans)
            tmp = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=self.path.parent,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(
                        {"version": 1, "plans": [p.to_dict() for p in self.plans]},
                        stream,
                        ensure_ascii=False,
                        indent=1,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, self.path)
                tmp = None
                return True
            except Exception:                                # noqa: BLE001 - task persistence must not stop a task, but must be observable
                _LOGGER.exception("Could not save task state to %s", self.path)
                return False
            finally:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        _LOGGER.debug("Could not remove temporary task file %s", tmp, exc_info=True)

    def active(self, session_id: str | None = None) -> TaskPlan | None:
        """Return only the unfinished task owned by the requested chat session."""
        owner = None if session_id is None else str(session_id)
        with self.lock:
            for p in reversed(self.plans):
                if owner is not None and p.session_id != owner:
                    continue
                if p.status in ACTIVE or (p.status == P_FAILED and time.time() - p.updated <= STALE_AFTER):
                    return p
        return None

    def get(self, plan_id: str, *, session_id: str | None = None) -> TaskPlan | None:
        owner = None if session_id is None else str(session_id)
        with self.lock:
            return next((
                p for p in self.plans
                if p.id == plan_id and (owner is None or p.session_id == owner)
            ), None)

    def latest(self, session_id: str | None = None) -> TaskPlan | None:
        with self.lock:
            return self.active(session_id) or next(
                (p for p in reversed(self.plans) if session_id is None or p.session_id == str(session_id)),
                None,
            )

    def new(self, goal: str, *, session_id: str = "") -> TaskPlan:
        with self.lock:
            plan = TaskPlan(f"t{uuid.uuid4().hex[:16]}", _safe(goal, 240))
            plan.session_id = str(session_id or "")
            self.plans.append(plan)
            self.plans = self._trim_history(self.plans)
            return plan

    def clear(self, session_id: str | None = None):
        with self.lock:
            if self._load_failed and session_id is not None:
                _LOGGER.error(
                    "Cannot safely clear task history for Session %s because %s contains unreadable records",
                    session_id,
                    self.path,
                )
                return
            if session_id is None:
                self.plans = []
            else:
                owner = str(session_id)
                self.plans = [plan for plan in self.plans if plan.session_id != owner]
            if self.path is not None:
                if self.plans:
                    self.save()
                else:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass


# ---------------------------------------------------------------------------------------------------- generic result status checks
def verify(tool: str, args: dict, status: str, text: str) -> tuple:
    """Return only facts code can establish without understanding the user's goal.

    Semantic postcondition review belongs to the model and is evidence-checked by
    planner.parse_review(). Tool-specific success heuristics do not live here.
    """
    if status != OK:
        return "unmet", f"the tool returned {status}"
    if not str(text or "").strip():
        return "unmet", "the tool returned an empty result"
    return "unverified", "execution returned successfully; goal completion still requires semantic evidence review"

_TRANSIENT_RX = re.compile(r"winerror\s*(?:32|33|170|1117|1450|21)\b|timed?\s*out|timeout|temporar|busy|try again|مشغول|در حال استفاده|موقت|قطع شد|دوباره تلاش", re.I)
_MISSING_RX = re.compile(r"پیدا نشد|وجود ندارد|یافت نشد|not found", re.I)


def classify_error(status: str, text: str) -> str:
    """'confirm' | 'transient' | 'missing' | 'permanent'. Only 'transient' may be retried, and only for read-only tools (agent decides)."""
    if status == NEEDS_CONFIRM:
        return "confirm"
    if status in (DENIED, UNKNOWN, BAD_ARGS):
        return "permanent"
    if status == ERROR:
        if _TRANSIENT_RX.search(text or ""):
            return "transient"
        if _MISSING_RX.search(text or ""):
            return "missing"
    return "permanent"


def summarize_result(tool: str, status: str, text: str) -> str:
    """The ONE line about a result that may be shown in the plan and written to disk. File content is never part of it."""
    body = str(text or "").strip()
    if status != OK:
        return ""
    if tool == "read_file":
        return f"فایل خوانده شد ({len(body)} نویسه؛ محتوا ذخیره نمی‌شود)"
    first = body.splitlines()[0] if body else ""
    return _safe(first, 200)


# ---------------------------------------------------------------------------------------------------- user commands during a task
_N = str.maketrans({"ي": "ی", "ك": "ک", "‌": " ", "‏": " "})
STATUS_RX = re.compile(r"تا\s*کجا\s*رسید|چقدر\s*(?:مونده|باقی|مانده)|گزارش\s*(?:پیشرفت|کار|وظیفه)|پیشرفت\s*(?:کار|وظیفه)?|وضعیت\s*(?:کار|وظیفه|تسک|مرحله)|کار\s*به\s*کجا|"
                       r"چی\s*شد\s*(?:کار)?$|\bprogress\b|task\s*status|status\s*of\s*the\s*task", re.I)
PAUSE_RX = re.compile(r"^(?:لطفا\s*)?(?:متوقف\s*کن|متوقفش\s*کن|توقف|صبر\s*کن|وایسا|نگه\s*دار|pause|stop|بسه)$|(?:کار|وظیفه|تسک)\s*(?:رو|را)?\s*(?:متوقف|نگه\s*دار)", re.I)
CANCEL_RX_TASK = re.compile(r"(?:کار|وظیفه|تسک)\s*(?:رو|را)?\s*(?:لغو|کنسل|رها)|لغو\s*(?:کار|وظیفه|تسک|همه)|بی\s*خیال\s*(?:کار|وظیفه|این)|cancel\s*(?:the\s*)?task|^(?:لغو|کنسل|cancel)$", re.I)
RESUME_RX = re.compile(r"^(?:لطفا\s*)?(?:ادامه(?:\s*(?:بده|کن|اش\s*بده|ش\s*بده|ی\s*کار))?|دوباره\s*ادامه\s*بده|برو\s*جلو|بقیه(?:\s*اش|ش)?(?:\s*رو)?\s*(?:انجام\s*بده|ادامه\s*بده)?|continue|resume|go\s*on)$", re.I)
# U+FF1A is the fullwidth colon, accepted as a separator next to ":" and "-".
ADD_STEP_RX = re.compile(r"^(?:یه|یک)?\s*مرحله(?:\s*(?:ی)?\s*(?:جدید|دیگه|دیگر))?\s*(?:هم\s*)?اضافه\s*کن\s*[:\uff1a\-]?\s*(.+)$|^add\s*(?:a\s*)?step\s*[:\uff1a\-]?\s*(.+)$", re.I)
CHANGE_RX = re.compile(r"^(?:نه\s*نه|نه|راستی|در\s*واقع|ببخشید|ولش\s*کن)\b.{4,}|(?:به\s*جاش|بجاش|به\s*جای|بجای)\s+.{3,}|هدف(?:\s*(?:رو|را))?\s*(?:عوض|تغییر)", re.I)


def parse_control(text: str) -> tuple:
    """-> (kind, payload) | (None, ''). Called only while an unfinished task exists. Conservative: only short, explicit phrases."""
    t = re.sub(r"\s+", " ", str(text or "").lower().translate(_N)).strip(" .!؟?،,")
    if not t:
        return None, ""
    words = len(t.split())
    m = ADD_STEP_RX.match(t)
    if m:
        return "add_step", (m.group(1) or m.group(2) or "").strip()
    if words <= 7 and CANCEL_RX_TASK.search(t):
        return "cancel", ""
    if words <= 7 and RESUME_RX.match(t):
        return "resume", ""
    if words <= 6 and PAUSE_RX.search(t):
        return "pause", ""
    if words <= 9 and STATUS_RX.search(t):
        return "status", ""
    if words >= 3 and CHANGE_RX.search(t):
        return "change", str(text).strip()
    return None, ""
