"""ToolAgent: connects the tool registry to the Hybrid Brain.

One user turn =  request -> (tool needed?) -> model writes a tool block -> tool runs -> REAL result goes back to the model ->
final natural answer.  The loop talks to the router only through HybridRouter.chat_stream, so every Provider / Route / Failover
behaves exactly as before; the chat history is never touched by intermediate tool messages (only the final answer is saved by the
caller as usual).

Safety rules enforced here, in code (not by trusting the model):
  * the model never runs a level-3 tool: it only gets "needs_confirmation"; the user's own next message ("تأیید") runs the exact
    arguments that were stored, once, within 5 minutes;
  * an identical call in the same user turn is answered from its first result and never executed twice;
  * a tool call cut off by a broken connection is never executed;
  * if the model fails after tools already ran, the user still gets the real tool results.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace

from . import protocol
from .autonomy import AutonomyMixin
from .access import PathPolicy
from .builtin import build_registry
from .registry import ToolResult, NEEDS_CONFIRM, BAD_ARGS, OK, LEVEL_NAMES, clip
from ..webintel.session import CANCEL as WEB_CANCEL
from ..game_mode_policy import tool_categories_allowed

CONFIRM_TTL = 300                 # seconds a pending confirmation stays valid
MEMO_TTL = 1800                   # seconds a "recent tool result" note stays in the prompt (session only, never saved)
MEMO_MAX_CHARS = 900
TOOL_LABELS = {
    "get_datetime": "خواندن ساعت سیستم", "get_system_info": "خواندن مشخصات سیستم", "get_resource_usage": "خواندن مصرف منابع",
    "get_disks": "خواندن فضای درایوها", "get_network_info": "بررسی شبکه و اینترنت", "list_running_apps": "فهرست برنامه‌های باز",
    "get_active_window": "خواندن پنجره‌ی فعال", "find_app": "جست‌وجوی برنامه", "list_allowed_folders": "پوشه‌های مجاز",
    "search_files": "جست‌وجوی فایل", "list_folder": "فهرست پوشه", "file_info": "اطلاعات فایل", "read_file": "خواندن فایل",
    "open_app": "باز کردن برنامه", "open_path": "باز کردن فایل/پوشه", "open_url": "باز کردن لینک",
    "bluetooth_status": "بررسی وضعیت بلوتوث", "bluetooth_on": "روشن کردن بلوتوث", "bluetooth_off": "خاموش کردن بلوتوث", "windows_control_info": "جدول دسترسی‌ها و عملیات اخیر",
    "make_folder": "ساخت پوشه", "create_file": "ساخت فایل", "append_text": "افزودن متن به فایل", "copy_item": "کپی فایل/پوشه", "rename_item": "تغییر نام",
    "write_file": "جایگزینی محتوای فایل (نیازمند تأیید)", "delete_folder": "حذف پوشه (نیازمند تأیید)", "batch_files": "عملیات گروهی روی فایل‌ها (نیازمند تأیید)",
    "organise_folder": "مرتب‌سازی پوشه (نیازمند تأیید)", "undo_file_operation": "برگرداندن آخرین عملیات فایل (نیازمند تأیید)",
    "delete_file": "حذف فایل (نیازمند تأیید)", "move_file": "انتقال فایل (نیازمند تأیید)",
    "agent_ask": "سپردن کار به ایجنت (نیازمند تأیید)", "agent_status": "وضعیت کار ایجنت", "agent_answer": "ارسال جواب کاربر به ایجنت",
    "window_list": "فهرست پنجره‌ها", "window_active": "پنجره‌ی فعال", "window_focus": "آوردن پنجره به جلو", "window_close": "بستن پنجره", "window_set_state": "تغییر اندازه‌ی پنجره",
    "type_text": "تایپ متن", "press_keys": "زدن کلید", "clipboard_set": "قرار دادن متن در کلیپ‌بورد", "clipboard_get": "خواندن کلیپ‌بورد (نیازمند تأیید)",
    "ui_list_controls": "فهرست کنترل‌های پنجره", "ui_click": "کلیک روی کنترل", "ui_click_confirmed": "کلیک روی کنترل حساس (نیازمند تأیید)",
    "ui_set_text": "پر کردن فیلد متنی", "mouse_click": "کلیک روی نقطه (نیازمند تأیید)",
    "agent_stop": "توقف کار ایجنت", "agent_health": "بررسی ایجنت", "mcp_info": "وضعیت سرورهای MCP",
    "web_search": "جست‌وجوی وب", "web_read": "خواندن صفحه‌ی وب", "web_research": "تحقیق چندمنبعی در وب", "web_research_status": "وضعیت تحقیق وب",
}
_NORM = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " ", "\u200f": " "})
# A confirmation is ONLY a bare "yes" (optionally with polite filler). A message that names an operation ("حذفش کن", "delete it", "فایل دیگه رو پاک کن")
# is a NEW request, never a confirmation of the pending one: the pending question is dropped and the new message is handled normally.
_CONFIRM_CORE = ("تایید می کنم", "تأیید می کنم", "تاییدش می کنم", "تایید", "تأیید", "تاییده", "تأییده", "بله", "بلی", "آره", "اره", "اوکی", "باشه", "درسته", "انجام بده",
                 "انجامش بده", "انجام بدید", "ok", "okay", "yes", "yep", "yeah", "confirm", "confirmed", "sure", "go ahead", "do it")
_CONFIRM_FILLER = ("لطفا", "لطفاً", "ممنون", "مرسی", "همین", "همینو", "همین رو", "خب", "خوب", "دیگه", "هم", "please", "thanks", "thank you", "then", "now")
_CORE_RX = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(w) for w in sorted(_CONFIRM_CORE, key=len, reverse=True)) + r")(?![\w])")
_FILLER_RX = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(w) for w in sorted(_CONFIRM_FILLER, key=len, reverse=True)) + r")(?![\w])")


def is_bare_confirmation(t: str) -> bool:
    """True only for a message that consists of nothing but confirmation words (already lower-cased / normalised, punctuation stripped)."""
    if not _CORE_RX.search(t):
        return False
    rest = _FILLER_RX.sub(" ", _CORE_RX.sub(" ", t))
    return not re.sub(r"[\s.!؟?،,؛;:~\-]+", "", rest)


CANCEL_RX = re.compile(r"(?:\bنه\b|نکن|لغو|کنسل|منصرف|بیخیال|بی\s*خیال|نخیر|\bno\b|cancel|don'?t|stop|never\s*mind)", re.I)


@dataclass
class ToolPlan:
    categories: set
    strong: bool = False              # the request clearly concerns this PC: automatic web search is skipped for it
    complex: bool = False             # looks multi-step (or a task is being continued): goes through the planner (autonomy.py)
    resume: bool = False              # continue / answer an unfinished task instead of planning a new one
    reasons: tuple = ()
    web: bool = False                 # the request is a web research / page reading request (the tool route handles it, the old one-shot auto search is skipped)


@dataclass
class Pending:
    tool: str
    args: dict
    summary: str
    created: float = field(default_factory=time.time)
    step_id: int | None = None        # the step of a task this confirmation belongs to (autonomy.py)
    plan_id: str = ""


class ToolAgent(AutonomyMixin):
    def __init__(self, settings: dict, data_dir=None, program_root=None):
        self.settings = settings
        self.policy = PathPolicy(settings, data_dir, program_root)
        self.registry = build_registry(self.policy)
        self._competitive_safe_mode = False
        self.registry.execution_guard = self._game_mode_execution_guard
        self.registry.access.require_grants = True           # production: a confirmed execution needs a grant made from the user's own confirmation message
        self.mcp = None
        try:                                              # external MCP servers + independent agents (kira/mcp); optional, in the background
            from .. import mcp as _mcp
            self.mcp = _mcp.install(self.registry, data_dir or self.policy.data_dir, lambda: self.settings)
        except Exception:                                 # noqa: BLE001
            self.mcp = None
        self._cancel = threading.Event()
        self._turn_id = 0
        self._turn_cache: dict[str, ToolResult] = {}
        self._memos: deque = deque(maxlen=6)
        self._pending: Pending | None = None
        self._pending_new = False
        self._last_cats: set = set()
        self._last_used_turn = -99
        self.last_results: list[ToolResult] = []
        self._init_autonomy(data_dir)            # task plans, task state, user control of a running task

    # ------------------------------------------------------------ game-mode permission boundary
    def set_competitive_safe_mode(self, enabled: bool):
        """Restrict local control tools while an online/PvP safety profile is active."""
        self._competitive_safe_mode = bool(enabled)
        if self._competitive_safe_mode:
            self.registry.access.revoke_grants()
            pending = self._pending
            if pending is not None:
                tool = self.registry.get(pending.tool)
                if tool is None or not tool_categories_allowed("competitive_safe", tool.categories):
                    self._pending = None

    def _game_mode_execution_guard(self, tool):
        """The ONE app-level gate for tool execution (ToolRegistry.execution_guard). It must hold on every path,
        including AutoAgent tools and direct shell / file access: fail closed, never bypassed."""
        if self.mode() == "off":
            return ("ابزارها خاموش است (tools_mode = off)؛ هیچ ابزاری اجرا نمی‌شود. "
                    "برای اجرای ابزار، حالت ابزارها را در تنظیمات از Off خارج کن.")
        if self._competitive_safe_mode and not tool_categories_allowed("competitive_safe", tool.categories):
            return ("Competitive Safe دسترسی ابزارهای محلی و کنترلی، دسکتاپ، برنامه‌ها، فایل‌ها، MCP و Agent را مسدود کرده است. "
                    "فقط ابزارهای وب مستقل مجازند.")
        return None

    # ------------------------------------------------------------ settings
    def set_settings(self, settings: dict):
        self.settings = settings
        self.policy.settings = settings

    def mode(self) -> str:
        m = str(self.settings.get("tools_mode", "auto")).lower()
        return m if m in ("auto", "always", "off") else "auto"

    def enabled(self) -> bool:
        return self.mode() != "off"

    def max_rounds(self) -> int:
        try:
            return max(1, min(int(self.settings.get("tools_max_rounds", 4)), 6))
        except (TypeError, ValueError):
            return 4

    # ------------------------------------------------------------ planning (cheap, deterministic, no model call)
    def begin_turn(self):
        """Call once per NEW user message (not for the automatic plain retry of the same message)."""
        self._turn_id += 1
        self._turn_cache = {}
        self._pending_new = False
        self.last_results = []
        self._cancel.clear()
        WEB_CANCEL.clear()
        self._turn_reset()

    def plan(self, text: str) -> ToolPlan | None:
        """Does this message need the tool catalog in the prompt? None = ordinary chat: nothing is added (no context cost).
        A message that looks multi-step, or that continues an unfinished task, comes back flagged (complex / resume) for the planner."""
        self.registry.user_text = str(text or "")
        if self.mode() == "off":
            return None
        plan = self.decide(text, self._plan_simple(text))
        if plan is not None:
            if self._competitive_safe_mode:
                plan.categories.intersection_update({"web"})
                if not plan.categories:
                    return None
            plan.web = "web" in plan.categories and (bool(protocol.detect_categories(text) & {"web"}) or self._web_resume(text))
        return plan

    def _web_resume(self, text: str) -> bool:
        """A short 'continue' while a web research is paused."""
        ctx = getattr(self.registry, "web_context", None)
        cur = ctx.store.current() if ctx else None
        return bool(cur is not None and cur.status == "paused" and len(str(text).split()) <= 6 and re.search(r"ادامه|بده|بزن|continue|resume", str(text), re.I))

    def _plan_simple(self, text: str) -> ToolPlan | None:
        mode = self.mode()
        if mode == "off":
            return None
        if mode == "always":
            return ToolPlan(set(protocol.ALL_CATEGORIES), protocol.is_strong(text))
        cats = protocol.detect_categories(text)
        if not cats and self._web_resume(text):
            cats = {"web"}                                   # "ادامه بده" while a web research is paused
        if not cats and self._turn_id - self._last_used_turn <= 2 and len(str(text).split()) <= 10:
            cats = set(self._last_cats)                      # a short follow-up to a tool turn ("بازش کن", "اولیش")
        return ToolPlan(cats, protocol.is_strong(text)) if cats else None

    def temperature(self, temperature: float) -> float:
        return min(float(temperature), 0.4)                  # tool blocks and exact facts do not need a high temperature

    def tools_block(self, plan: ToolPlan, last_round: bool = False) -> str:
        if last_round:
            return protocol.build_block("", last_round=True)
        extra = ""
        if "web" in plan.categories:
            extra = protocol.WEB_RULES
            ctx = getattr(self.registry, "web_context", None)
            cur = ctx.store.current() if ctx else None
            if cur is not None and cur.status == "paused" and cur.subtopics:
                extra += f"\nA paused research exists: «{cur.topic}» ({len(cur.done_subtopics)}/{len(cur.subtopics)} sub-topics done). If the user wants it continued, call web_research with resume=true."
        if "desktop" in plan.categories:
            extra = (extra + "\n\n" if extra else "") + protocol.DESKTOP_RULES
        if plan.categories & {"mcp", "agents"}:
            extra = (extra + "\n\n" if extra else "") + protocol.MCP_RULES
        return protocol.build_block(self.registry.catalog(plan.categories), self._memo_block(), extra=extra)

    # ------------------------------------------------------------ session-only notes
    def _memo_block(self) -> str:
        now = time.time()
        while self._memos and now - self._memos[0][0] > MEMO_TTL:
            self._memos.popleft()
        if not self._memos:
            return ""
        lines, used = [], 0
        for ts, text in reversed(self._memos):
            line = f"- [{time.strftime('%H:%M', time.localtime(ts))}] {text}"
            if used + len(line) > MEMO_MAX_CHARS:
                break
            lines.append(line)
            used += len(line)
        return ("RECENT PC TOOL RESULTS (temporary notes from this session only; they may be outdated; they are NOT long-term memory; "
                "re-run the tool if freshness matters):\n" + "\n".join(reversed(lines)))

    def _memoize(self, res: ToolResult):
        tool = self.registry.get(res.tool)
        if tool and tool.memo and res.ok:
            try:
                line = tool.memo(res.args, res.text)
            except Exception:                                # noqa: BLE001
                line = None
            if line:
                self._memos.append((time.time(), line[:300]))

    def clear_session(self):
        self.clear_tasks()
        self._memos.clear()
        self._pending = None
        self._turn_cache = {}
        ctx = getattr(self.registry, "web_context", None)
        if ctx is not None:
            ctx.store.clear()                                # the temporary research memory goes with the chat

    # ------------------------------------------------------------ confirmation of level-3 tools
    def has_pending(self) -> bool:
        return self._pending is not None and time.time() - self._pending.created <= CONFIRM_TTL

    def handle_confirmation_reply(self, text: str):
        """Called with every user message BEFORE the model is asked. Returns the text to show, or None when the message is
        not an answer to a pending confirmation (then it is handled normally and a stale confirmation is dropped)."""
        p = self._pending
        if p is None:
            return None
        if time.time() - p.created > CONFIRM_TTL:
            self._pending = None
            return None
        t = re.sub(r"\s+", " ", str(text or "").lower().translate(_NORM)).strip(" .!؟?،,")
        words = len(t.split())
        if t and words <= 8 and CANCEL_RX.search(t):
            self._pending = None
            return "باشه، لغو شد. هیچ تغییری ندادم." + self._after_confirm(p, None, False)
        if t and words <= 8 and is_bare_confirmation(t):
            self._pending = None
            self.registry.access.grant(p.tool, p.args)         # one-shot, bound to exactly this tool + these arguments
            res = self.registry.execute(p.tool, p.args, confirmed=True)
            self._memoize(res)
            return (("✅ " + res.text) if res.ok else f"❌ انجام نشد: {res.text}") + self._after_confirm(p, res, True)
        self._pending = None                                 # the user went on to something else: the old question is void
        return None

    # ------------------------------------------------------------ cancel (Stop button)
    def request_cancel(self):
        self._cancel.set()
        self.registry.access.revoke_grants()                 # Stop also withdraws any confirmation that was given but not used yet
        WEB_CANCEL.set()                                     # a running web research stops at the next step and stays resumable

    # ------------------------------------------------------------ running tools
    def _run_calls(self, calls, errors, on_tool):
        results = [ToolResult("?", BAD_ARGS, msg) for msg in errors]
        for call in calls[:protocol.MAX_CALLS_PER_ROUND]:
            if self._cancel.is_set():
                break
            name, args = call["tool"], call.get("args") or {}
            sig = name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
            if sig in self._turn_cache:                      # never repeat the same operation in one turn
                prev = self._turn_cache[sig]
                results.append(replace(prev, cached=True, text=prev.text + "\n[این همان فراخوانی قبلی است؛ دوباره اجرا نشد. از همین نتیجه استفاده کن.]"))
                continue
            label = TOOL_LABELS.get(name, name)
            if on_tool:
                on_tool({"phase": "tool_start", "tool": name, "label": label})
            res = self.registry.execute(name, args)
            self._turn_cache[sig] = res
            if res.status == NEEDS_CONFIRM:
                self._pending = Pending(res.tool, dict(res.args), res.summary)
                self._pending_new = True
            else:
                self._memoize(res)
            if on_tool:
                on_tool({"phase": "tool_done", "tool": name, "label": label, "status": res.status, "ms": res.ms})
            results.append(res)
        return results

    @staticmethod
    def _results_message(results) -> str:
        blocks = [protocol.result_block(r.tool, r.status, r.text) for r in results]
        return "\n\n".join(blocks) + "\n\n" + protocol.FOLLOW_UP

    @staticmethod
    def _plain_summary(results, reason: str) -> str:
        lines = [reason]
        for r in results:
            mark = "✅" if r.status == OK else ("⏸" if r.status == NEEDS_CONFIRM else "❌")
            lines.append(f"{mark} {TOOL_LABELS.get(r.tool, r.tool)} [{r.status}]:\n{clip(r.text, 700)}")
        return "\n\n".join(lines)

    # ------------------------------------------------------------ the turn loop
    def run(self, router, messages, system_prompt, temperature, plan, retry_index=0, on_chunk=None, on_event=None, on_tool=None):
        """Same return value as HybridRouter.chat_stream (a dict with 'text', 'stopped', 'interrupted', metrics...), plus 'tools' (and 'task').
        'text' is ONLY the final answer: tool blocks are never part of it and never reach the chat window.
        A multi-step request (plan.complex) goes through the planner (autonomy.py); everything else runs the original loop below."""
        if getattr(plan, "complex", False) and self.planning_enabled():
            return self.run_planned(router, messages, system_prompt, temperature, plan, retry_index, on_chunk, on_event, on_tool)
        return self._run_simple(router, messages, system_prompt, self.temperature(temperature), plan, retry_index, on_chunk or (lambda s: None), on_event, on_tool)

    def _run_simple(self, router, messages, system_prompt, temp, plan, retry_index, emit, on_event, on_tool):
        rounds = self.max_rounds()
        cur = list(messages)
        executed: list[ToolResult] = []
        last_res = None
        for rnd in range(rounds + 1):
            last = rnd == rounds
            prompt = system_prompt + "\n\n" + self.tools_block(plan, last_round=last)
            # Prefer provider-native function calling where the selected route supports the OpenAI tools schema.
            # Providers without a native adapter keep the existing text-protocol fallback unchanged.
            if not last and callable(getattr(router, "chat_with_tools", None)):
                try:
                    native = router.chat_with_tools(cur, prompt, temp, self.registry.schemas(plan.categories), on_event=on_event)
                except Exception as exc:                         # noqa: BLE001 - preserve real outcomes if a later native round fails
                    if not executed:
                        raise
                    text = self._plain_summary(executed, f"⚠️ ابزارها اجرا شدند ولی Native Function Calling شکست خورد ({str(exc)[:200]}). نتیجه‌ی واقعی:")
                    emit(text)
                    return self._final(last_res or {}, text, executed)
                if native is not None:
                    last_res = native
                    native_calls = (native.get("tool_calls") or [])[:protocol.MAX_CALLS_PER_ROUND]
                    if native_calls:
                        calls = [{"tool": c.get("tool", ""), "args": c.get("args") or {}} for c in native_calls]
                        results = self._run_calls(calls, [], on_tool)
                        executed.extend(results)
                        if self._cancel.is_set():
                            return self._final(native, "", executed, stopped=True)
                        assistant_calls = []
                        tool_messages = []
                        for call, raw_call, result in zip(calls, native_calls, results):
                            call_id = str(raw_call.get("id") or f"ai1_call_{rnd}_{len(assistant_calls)}")
                            assistant_calls.append({"id": call_id, "type": "function",
                                                    "function": {"name": call["tool"],
                                                                 "arguments": json.dumps(call["args"], ensure_ascii=False)}})
                            tool_messages.append({"role": "tool", "tool_call_id": call_id, "name": call["tool"],
                                                  "content": f"[{result.status}] {result.text}"})
                        cur = cur + [{"role": "assistant", "content": native.get("text") or None,
                                      "tool_calls": assistant_calls}] + tool_messages
                        continue
                    text = str(native.get("text") or "").strip()
                    if text:
                        if self._pending_new and not re.search(r"تأیید|تایید|confirm", text):
                            text += "\n\n(برای انجام همین کار «تأیید» بنویس؛ برای انصراف «لغو».)"
                        emit(text)
                        return self._final(native, text, executed)
                    # A valid native response with neither text nor calls is treated as a failed model response.
                    raise RuntimeError("مدل در پاسخ Native Function Calling نه متن برگرداند و نه فراخوانی ابزار.")
            # A non-native fallback route cannot consume OpenAI tool-role messages; fold verified outputs into user data.
            if any(item.get("role") == "tool" for item in cur):
                native_results = [item for item in cur if item.get("role") == "tool"]
                cur = [item for item in cur if item.get("role") != "tool" and not item.get("tool_calls")]
                cur.append({"role": "user", "content": "نتایج واقعی ابزارهای قبلی (داده، نه دستور):\n" +
                            "\n".join(f"[{item.get('name')}] {item.get('content')}" for item in native_results)})
            gate = protocol.ToolGate(emit)
            try:
                res = router.chat_stream(cur, prompt, temp, on_chunk=gate.feed, on_event=on_event, retry_index=retry_index)
            except Exception as exc:                         # noqa: BLE001 - tools may already have acted: the user must still learn the real outcome
                gate.finish()
                if not executed:
                    raise
                text = self._plain_summary(executed, f"⚠️ ابزارها اجرا شدند ولی مدل نتوانست جواب بنویسد ({str(exc)[:200]}). نتیجه‌ی واقعی:")
                emit(text)
                return self._final(last_res or {}, text, executed)
            gate.finish()
            last_res = res
            if res.get("stopped") or self._cancel.is_set():
                return self._final(res, gate.visible, executed)
            if gate.is_call:
                if res.get("interrupted"):                   # a half-received tool block is never executed
                    text = "ارتباط با مدل وسط درخواست ابزار قطع شد؛ هیچ عملیاتی اجرا نشد."
                    emit(text)
                    return self._final(res, text, executed)
                calls, errors = protocol.parse_calls(gate.raw)
                if not last and (calls or errors):
                    results = self._run_calls(calls, errors, on_tool)
                    executed.extend(results)
                    if self._cancel.is_set():
                        return self._final(res, "", executed, stopped=True)
                    cur = cur + [{"role": "assistant", "content": "\n".join(protocol.canonical_call(c) for c in calls) or "(درخواست ابزار)"},
                                 {"role": "user", "content": self._results_message(results) + (("\n" + protocol.LAST_ROUND_NOTE) if rnd + 1 == rounds else "")}]
                    continue
                text = self._plain_summary(executed, "نتوانستم از ابزارها به جواب نهایی برسم.") if executed else \
                    "درخواست ابزار قابل اجرا نبود و چیزی اجرا نشد."
                emit(text)
                return self._final(res, text, executed)
            text = gate.visible
            if self._pending_new and not re.search(r"تأیید|تایید|confirm", text):
                footer = "\n\n(برای انجام همین کار «تأیید» بنویس؛ برای انصراف «لغو».)"
                emit(footer)
                text += footer
            return self._final(res, text, executed)
        return self._final(last_res or {}, "", executed)

    def _final(self, res: dict, text: str, executed, stopped=None, task=None) -> dict:
        out = dict(res or {})
        out["text"] = text
        if task is not None:
            done, total = task.counts()
            out["task"] = {"id": task.id, "status": task.status, "done": done, "total": total}
        out["tools"] = [{"tool": r.tool, "status": r.status, "level": LEVEL_NAMES.get(r.level, "?"), "ms": r.ms, "cached": r.cached} for r in executed]
        out.setdefault("stopped", False)
        out.setdefault("interrupted", None)
        if stopped is not None:
            out["stopped"] = stopped
        self.last_results = list(executed)
        if any(r.status != BAD_ARGS and r.tool != "?" for r in executed):
            cats = set()
            for r in executed:
                t = self.registry.get(r.tool)
                if t:
                    cats |= set(t.categories)
            self._last_cats, self._last_used_turn = cats, self._turn_id
        return out
