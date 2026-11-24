"""Unified System Access Manager (T5-Core): the ONE place that decides what Kira may do on this PC, whether the user must confirm it, which
backend runs it, and what really happened.

Every tool - Windows control (apps / Bluetooth / audio / desktop), file agent, web, MCP, agents - passes through ToolRegistry.execute(), and
execute() asks this manager. No module has (or may create) a permission system of its own; a module only DECLARES its operation (permission
level, explicit-request gate, backend) and the manager enforces it. Nothing here knows about a Provider or a model.

Permission levels
  READ       reads / looks up information. Runs when the user asks.
  CONTROL    ordinary, reversible control of apps and Windows (volume, window state, open an app, Bluetooth, typing into a window ...).
             No repeated confirmation; sensitive ones carry an explicit-request gate (the user's CURRENT message must ask for it).
  FILE       ordinary file / folder management that is reversible or non-destructive (create, copy, rename, append). Same gates as CONTROL
             and always inside PathPolicy (allowed folders, never secrets).
  ELEVATED   needs Administrator rights. ALWAYS confirmed, and the elevation (UAC) is requested only for that one operation, never kept.
             (No capability uses it yet; the policy, confirmation and journal are ready. See docs/SYSTEM_ACCESS_FA.md.)
  PROTECTED  sensitive, destructive or irreversible (delete, overwrite, raw mouse click, clipboard read, external agents ...). ALWAYS confirmed.

Rules enforced in code (not by trusting the model)
  * Confirmation is bound to the exact tool AND arguments: the agent grants it only when the user's own message is a bare confirmation, the
    grant is one-shot, expires, is cleared by Stop, and is checked again inside execute(). A different argument = a different operation.
  * Explicit-request gate (`intent_rx`): the user's CURRENT message must ask for the operation; a model cannot trigger it on its own.
  * Taint: after a tool returned EXTERNAL content in this turn (web page, file text, MCP / agent output) every CONTROL / FILE operation that
    has no explicit-request gate needs a confirmation, so text inside a page or document cannot make Kira open / do something silently.
  * Backends: an operation names its backend (win32, uia, com, sendinput, powershell-fixed, winrt, ...). Alternative backends can be chained;
    a backend that is not available hands over to the next one, and the one that really ran is journaled. No free PowerShell exists.
  * Journal: every call - allowed, denied, needing confirmation, failed - is recorded with its real result (memory only, never on disk).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .registry import ToolError, redact_secrets, READ, ACTION, SENSITIVE

# ------------------------------------------------------------------ permission levels
READ_P, CONTROL, FILE, ELEVATED, PROTECTED = 1, 2, 3, 4, 5
PERMISSION_NAMES = {READ_P: "READ", CONTROL: "CONTROL", FILE: "FILE", ELEVATED: "ELEVATED", PROTECTED: "PROTECTED"}
PERMISSION_FA = {READ_P: "فقط خواندن", CONTROL: "کنترل عادی", FILE: "مدیریت فایل", ELEVATED: "نیازمند Administrator", PROTECTED: "حساس/برگشت‌ناپذیر"}
CONFIRM_FROM = ELEVATED                       # ELEVATED and PROTECTED always need the user's explicit confirmation

BACKENDS = {"win32": "Windows API", "uia": "UI Automation", "com": "COM / Core Audio", "sendinput": "SendInput", "powershell-fixed": "PowerShell ثابت و کنترل‌شده",
            "winrt": "Windows Runtime", "filesystem": "فایل‌سیستم (PathPolicy)", "network": "شبکه (netguard)", "external": "MCP / ایجنت خارجی", "python": "کد داخلی Kira"}

GRANT_TTL = 300.0
JOURNAL_SIZE = 300
EXTERNAL_TOOL_NAMES = {"read_file"}           # their RESULT is content written by somebody else
EXTERNAL_CATEGORIES = {"web", "mcp", "agents"}
PRIVATE_PARAMS = {"text", "content", "body", "password", "secret", "token", "key", "quote", "message"}
_STATUS_FA = {"ok": "موفق", "error": "خطا", "denied": "رد شد", "needs_confirmation": "منتظر تأیید", "bad_args": "ورودی نادرست", "unknown_tool": "ابزار ناشناخته"}


class BackendUnavailable(Exception):
    """Raised by a backend that cannot run on this PC (missing API, blocked, wrong Windows version): the next backend is tried."""


@dataclass(frozen=True)
class Policy:
    permission: int
    domain: str
    backend: str
    intent_rx: object
    external: bool
    verifies: bool
    intent_alt: object = None

    @property
    def name(self) -> str:
        return PERMISSION_NAMES[self.permission]

    @property
    def always_confirm(self) -> bool:
        return self.permission >= CONFIRM_FROM


def _digest(tool: str, args: dict) -> str:
    return hashlib.sha256((tool + "\0" + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " "))


class Journal:
    """In-memory record of what was really done (never written to disk, never part of the chat history)."""

    def __init__(self, size: int = JOURNAL_SIZE):
        self._items: deque = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, **entry):
        entry.setdefault("ts", time.time())
        with self._lock:
            self._items.append(entry)

    def recent(self, n: int = 10) -> list[dict]:
        with self._lock:
            return list(self._items)[-n:]


def _args_brief(args: dict) -> str:
    parts = []
    for k, v in (args or {}).items():
        if k in PRIVATE_PARAMS:
            parts.append(f"{k}=<{len(str(v))} نویسه>")
        else:
            parts.append(f"{k}={str(v)[:60]}")
    return redact_secrets(", ".join(parts))[:160]


@dataclass
class _AccessTurnState:
    user_text: str = ""
    tainted: bool = False
    grants: dict[str, float] = field(default_factory=dict)


class AccessManager:
    def __init__(self, registry):
        self.registry = registry
        self.journal = Journal()
        self._lock = threading.RLock()
        self._fallback_state = _AccessTurnState()
        self._session_states: dict[str, _AccessTurnState] = {}
        self._session_context = ContextVar(
            f"access_session_{id(self)}", default=""
        )
        # True in the real application (ToolAgent turns it on): a confirmed execute() then needs a grant that the agent created from the user's own
        # bare confirmation. A bare ToolRegistry (development / unit tests) keeps accepting confirmed=True from its caller.
        self.require_grants = False
        self._local = threading.local()

    def _state_for(self, session_id: str | None = None) -> _AccessTurnState:
        owner = self._session_context.get() if session_id is None else str(session_id or "")
        if not owner:
            return self._fallback_state
        with self._lock:
            return self._session_states.setdefault(owner, _AccessTurnState())

    @contextmanager
    def use_session(self, session_id: str):
        """Bind intent, taint and confirmation grants to one character's Chat Session."""
        token = self._session_context.set(str(session_id or ""))
        try:
            yield self._state_for()
        finally:
            self._session_context.reset(token)

    def release_session(self, session_id: str) -> bool:
        """Drop ephemeral access intent and grants after the owning Session is fully drained."""
        owner = str(session_id or "")
        if not owner:
            return False
        with self._lock:
            state = self._session_states.pop(owner, None)
            if state is not None:
                state.grants.clear()
        return state is not None

    # Compatibility accessors preserve the legacy no-session API while ToolAgent
    # executes every request inside use_session().
    @property
    def _turn_text(self) -> str:
        return self._state_for().user_text

    @_turn_text.setter
    def _turn_text(self, value: str) -> None:
        self._state_for().user_text = str(value or "")

    @property
    def _tainted(self) -> bool:
        return self._state_for().tainted

    @_tainted.setter
    def _tainted(self, value: bool) -> None:
        self._state_for().tainted = bool(value)

    @property
    def _grants(self) -> dict[str, float]:
        return self._state_for().grants

    # ------------------------------------------------------------ policy
    @staticmethod
    def policy_for(tool) -> Policy:
        """The policy of any tool. A capability declares it; a plain registry Tool gets it from its legacy level (READ / ACTION / SENSITIVE)."""
        perm = int(getattr(tool, "permission", 0) or 0)
        if perm not in PERMISSION_NAMES:
            if tool.level >= SENSITIVE:
                perm = PROTECTED
            elif tool.level >= ACTION:
                perm = FILE if "files" in tool.categories else CONTROL
            else:
                perm = READ_P
        cats = set(tool.categories or ())
        domain = getattr(tool, "domain", "") or ("files" if "files" in cats else "web" if "web" in cats else "mcp" if cats & {"mcp", "agents"} else
                                               sorted(cats)[0] if cats else "system")
        external = bool(getattr(tool, "external", False)) or tool.name in EXTERNAL_TOOL_NAMES or bool(cats & EXTERNAL_CATEGORIES)
        backend = getattr(tool, "backend", "") or ("filesystem" if domain == "files" else "network" if domain == "web" else "external" if cats & {"mcp", "agents"} else "python")
        return Policy(perm, domain, backend, getattr(tool, "intent_rx", None), external, bool(getattr(tool, "verifies_result", False)), getattr(tool, "intent_alt", None))

    # ------------------------------------------------------------ turn state (taint)
    def begin_turn(self, user_text: str):
        with self._lock:
            self._turn_text = str(user_text or "")
            self._tainted = False

    @property
    def session_id(self) -> str:
        """Current Session owner; empty outside a ToolAgent session scope."""
        return str(self._session_context.get() or "")

    @property
    def user_text(self) -> str:
        return self._turn_text

    @property
    def tainted(self) -> bool:
        return self._tainted

    def check_intent(self, tool, pol: Policy) -> bool:
        if pol.intent_rx is None:
            return True
        text = _norm_text(self._turn_text)
        if pol.intent_rx.search(text):
            return True
        try:
            return bool(pol.intent_alt and pol.intent_alt(text))
        except Exception:                                  # noqa: BLE001 - a broken helper never opens the gate
            return False

    def confirmation_reason(self, tool, pol: Policy) -> str:
        """'' when no confirmation is needed, else why one is (shown to the user)."""
        if pol.always_confirm:
            return "elevated" if pol.permission == ELEVATED else "protected"
        if self._tainted and pol.permission in (CONTROL, FILE):
            # A keyword intent guard is not an argument-level authorization:
            # external content can steer a broad "create/open" request toward a
            # different target, so every state-changing action needs confirmation.
            return "tainted"
        return ""

    # ------------------------------------------------------------ one-shot confirmations bound to (tool, arguments)
    def grant(self, tool: str, args: dict):
        with self._lock:
            now = time.time()
            grants = self._grants
            for digest, expiry in tuple(grants.items()):
                if expiry <= now:
                    grants.pop(digest, None)
            grants[_digest(tool, args)] = now + GRANT_TTL

    def consume_grant(self, tool: str, args: dict) -> bool:
        with self._lock:
            exp = self._grants.pop(_digest(tool, args), 0.0)
            return exp > time.time()

    def revoke_grants(self, session_id: str | None = None):
        """Revoke one Session's grants, or every grant when called without an owner."""
        with self._lock:
            if session_id is None:
                self._fallback_state.grants.clear()
                for state in self._session_states.values():
                    state.grants.clear()
            else:
                self._state_for(str(session_id)).grants.clear()

    # ------------------------------------------------------------ backends
    def set_backend(self, name: str):
        self._local.backend = name

    def take_backend(self) -> str:
        name = getattr(self._local, "backend", "")
        self._local.backend = ""
        return name

    # ------------------------------------------------------------ recording
    def record(self, tool, pol: Policy, res, confirmed: bool = False, reason: str = ""):
        backend = self.take_backend() or pol.backend
        self.journal.add(tool=tool.name, domain=pol.domain, permission=pol.name, status=res.status, ms=res.ms, backend=backend,
                         confirmed=bool(confirmed and res.status == "ok" and (pol.always_confirm or reason == "tainted")),
                         verified=bool(pol.verifies and res.status == "ok"), args=_args_brief(res.args),
                         summary=redact_secrets(" ".join(str(res.text).split()))[:220])
        if pol.external and res.status in ("ok", "error"):
            with self._lock:
                self._tainted = True                         # even an external error message may contain attacker-controlled instructions

    # ------------------------------------------------------------ report (READ tool windows_control_info)
    @staticmethod
    def _report_int(value, default: int, minimum: int, maximum: int) -> int:
        """Parse untrusted model arguments without allowing malformed values to break discovery."""
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return max(minimum, min(maximum, parsed))

    def info_text(self, recent: int = 8, category: str = "", offset: int = 0, limit: int = 30,
                  name: str = "") -> str:
        tools = sorted(self.registry.all(), key=lambda t: (self.policy_for(t).permission, self.policy_for(t).domain, t.name))
        category = str(category or "").strip().lower()
        name = str(name or "").strip()
        if category:
            tools = [tool for tool in tools if category in {str(item).lower() for item in tool.categories}]
        if name:
            tools = [tool for tool in tools if tool.name.casefold() == name.casefold()]
            if not tools:
                return f"ابزار «{name[:100]}» در رجیستری فعلی پیدا نشد. نام دقیق را از فهرست ابزارها بردار."
        total = len(tools)
        offset = 0 if name else self._report_int(offset, 0, 0, 1_000_000)
        limit = 1 if name else self._report_int(limit, 30, 1, 40)
        page = tools[offset:offset + limit]
        next_offset = offset + len(page)
        more = next_offset < total
        lines = [
            "فهرست زندهٔ قابلیت‌های کیرا از رجیستری واقعی همین اجرا:",
            f"تعداد ابزارهای منطبق: {total} · نمایش: {offset + 1 if page else 0} تا {next_offset}",
            f"ادامه دارد: {more} · offset بعدی: {next_offset if more else 'ندارد'}",
            "برای جزئیات کامل یک ابزار، name را با نام دقیق همان ابزار فراخوانی کن.",
        ]
        for t in page:
            p = self.policy_for(t)
            gate = ("تأیید لازم" if p.always_confirm else "درخواست صریح لازم" if p.intent_rx is not None
                    else "پس از محتوای خارجی: تأیید" if p.permission in (CONTROL, FILE) else "فقط خواندن")
            categories = ", ".join(t.categories) or "بدون دسته"
            level_name = {READ: "READ", ACTION: "ACTION", SENSITIVE: "SENSITIVE"}.get(t.level, str(t.level))
            permission_name = PERMISSION_NAMES.get(p.permission, str(p.permission))
            backend = BACKENDS.get(p.backend, p.backend)
            if not name:
                lines.append(f"- {t.name} [{categories}] — {t.description[:180]} · {level_name}/{permission_name} · {backend} · {gate}")
                continue
            if t.params:
                params = []
                for arg in t.params:
                    required = "اجباری" if arg.required else "اختیاری"
                    detail = f"{arg.name} ({arg.type}، {required}): {arg.description or 'بدون توضیح'}"
                    if arg.enum:
                        detail += "؛ مقادیر مجاز: " + ", ".join(map(str, arg.enum))
                    params.append(detail)
                param_text = "؛ ".join(params)
            else:
                param_text = "بدون ورودی"
            lines.append(
                f"\n- {t.name} [{categories}]"
                f"\n  کاربرد: {t.description}"
                f"\n  ورودی‌ها: {param_text}"
                f"\n  سطح ابزار/مجوز: {level_name} / {permission_name} · دامنه: {p.domain} · Backend: {backend}"
                f"\n  شرط اجرا: {gate}"
                + (" · نتیجه دوباره بررسی می‌شود" if p.verifies else "")
            )
        recent = self._report_int(recent, 8, 0, 50)
        recent_items = [e for e in self.journal.recent(recent + 2) if e["tool"] != "windows_control_info"]
        items = recent_items[-recent:] if recent else []
        lines.append("")
        if items:
            lines.append(f"آخرین عملیات ثبت‌شده ({len(items)}):")
            for e in items:
                clock = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
                lines.append(f"- {clock} {e['tool']}({e['args']}) [{e['permission']}/{BACKENDS.get(e['backend'], e['backend'])}] ← {_STATUS_FA.get(e['status'], e['status'])}"
                             f"{' · تأییدشده' if e['confirmed'] else ''}{' · بازبینی‌شده' if e['verified'] else ''}: {e['summary'][:150]}")
        else:
            lines.append("هنوز عملیاتی در این اجرای برنامه ثبت نشده است.")
        return "\n".join(lines)



__all__ = ["AccessManager", "Policy", "Journal", "BackendUnavailable", "ToolError", "READ_P", "CONTROL", "FILE", "ELEVATED", "PROTECTED",
           "PERMISSION_NAMES", "BACKENDS", "READ"]
