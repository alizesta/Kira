"""Unified tool registry: one place that defines, validates and runs every Kira tool.

Nothing here knows about a model or a Provider. A tool is plain data (name, description, parameters, access level,
handler); the text protocol in protocol.py and the loop in agent.py are the only parts that talk to a model.

Access levels:
  READ       (1)  only reads information; runs when the user asks.
  ACTION     (2)  ordinary, low-risk actions (open an app / file / folder / link); runs when the user asks, inside fixed limits.
  SENSITIVE  (3)  changes or removes something; NEVER runs without the user's explicit confirmation (see agent.py).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

READ, ACTION, SENSITIVE = 1, 2, 3
LEVEL_NAMES = {READ: "read", ACTION: "action", SENSITIVE: "sensitive"}

OK, ERROR, DENIED, NEEDS_CONFIRM, BAD_ARGS, UNKNOWN = "ok", "error", "denied", "needs_confirmation", "bad_args", "unknown_tool"
DEFAULT_MAX_CHARS = 6000                 # a tool result is cut here so it never swallows a small context window


class ToolError(Exception):
    """A failure whose message is safe and useful to show (it goes to the model and to the user as the REAL reason)."""

    def __init__(self, message: str, status: str = ERROR):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "string"                 # string | integer | number | boolean
    description: str = ""
    required: bool = False
    default: Any = None
    enum: tuple = ()


@dataclass
class Tool:
    name: str
    description: str                     # one short line: it is shown to the model on every tool turn
    handler: Callable[[dict], str]
    params: tuple = ()
    level: int = READ
    categories: tuple = ()               # time | system | apps | files  (the catalog sent to the model is limited to what the request is about)
    confirm_summary: Callable[[dict], str] | None = None     # level 3: what exactly will happen, in plain Persian
    precheck: Callable[[dict], dict] | None = None           # level 3: validate / normalise the arguments BEFORE asking the user
    memo: Callable[[dict, str], str | None] | None = None    # short line worth keeping for follow-ups in this session only
    max_chars: int = DEFAULT_MAX_CHARS
    intent_rx: Any = None                # optional: the user's CURRENT message must match this regex, otherwise the tool refuses to run (explicit-request guard)

    def signature(self) -> str:
        parts = [f"{p.name}{'*' if p.required else '?'}: {p.type}" for p in self.params]
        return f"{self.name}({', '.join(parts)})"

    def catalog_line(self) -> str:
        tag = {READ: "", ACTION: " [action]", SENSITIVE: " [needs user confirmation]"}[self.level]
        return f"- {self.signature()} — {self.description}{tag}"

    def json_schema(self) -> dict:
        """OpenAI-style function schema. Not used by the text protocol; kept so a native function-calling adapter can be added later."""
        props = {}
        for p in self.params:
            entry = {"type": p.type, "description": p.description}
            if p.enum:
                entry["enum"] = list(p.enum)
            props[p.name] = entry
        return {"name": self.name, "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": [p.name for p in self.params if p.required]}}


@dataclass
class ToolResult:
    tool: str
    status: str
    text: str                            # exactly what the model sees
    args: dict = field(default_factory=dict)
    level: int = READ
    ms: int = 0
    summary: str = ""                    # level 3 needing confirmation: what will happen
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == OK


_TRUE = {"1", "true", "yes", "y", "on", "بله", "آره"}
_FALSE = {"0", "false", "no", "n", "off", "نه", "خیر"}


def _coerce(param: Param, value: Any) -> Any:
    if value is None:
        raise ValueError("مقدار خالی است")
    if param.type == "string":
        if isinstance(value, (dict, list)):
            raise ValueError("باید متن باشد")
        return str(value).strip()
    if param.type == "integer":
        if isinstance(value, bool):
            raise ValueError("باید عدد باشد")
        return int(float(str(value).strip()))
    if param.type == "number":
        return float(str(value).strip())
    if param.type == "boolean":
        if isinstance(value, bool):
            return value
        low = str(value).strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError("باید true یا false باشد")
    return value


_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}"),        # JWT
    re.compile(r"(?i)\b(?:api[_\- ]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{12,}"),
]


def redact_secrets(text: str) -> str:
    """Obvious keys / tokens inside a tool result are masked before the model (possibly a cloud one) sees them."""
    for rx in _SECRET_PATTERNS:
        text = rx.sub("[پنهان‌شده: شبیه کلید/رمز]", text)
    return text


def clip(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n[... خروجی بعد از {limit} نویسه بریده شد ...]"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self.user_text = ""               # the user's latest message (set by the agent each turn); used only by tools with intent_rx

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"ابزار «{tool.name}» قبلاً ثبت شده است.")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(str(name or "").strip())

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def for_categories(self, categories) -> list[Tool]:
        wanted = set(categories or ())
        return [t for t in self._tools.values() if not wanted or wanted & set(t.categories)]

    def catalog(self, categories=None) -> str:
        return "\n".join(t.catalog_line() for t in self.for_categories(categories))

    def schemas(self, categories=None) -> list[dict]:
        return [t.json_schema() for t in self.for_categories(categories)]

    # ---- validation ----
    def clean_args(self, tool: Tool, args: Any) -> dict:
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ToolError("آرگومان‌های ابزار باید یک شیء JSON باشند.", BAD_ARGS)
        known = {p.name: p for p in tool.params}
        out: dict[str, Any] = {}
        for key, value in args.items():
            param = known.get(key)
            if param is None:
                continue                                           # unknown arguments are ignored, never passed on
            if value is None or (isinstance(value, str) and not value.strip() and param.type != "string"):
                continue
            try:
                out[key] = _coerce(param, value)
            except (ValueError, TypeError) as exc:
                raise ToolError(f"آرگومان «{key}» درست نیست: {exc}.", BAD_ARGS) from exc
            if param.enum and out[key] not in param.enum:
                raise ToolError(f"آرگومان «{key}» باید یکی از این‌ها باشد: {', '.join(map(str, param.enum))}.", BAD_ARGS)
        missing = [p.name for p in tool.params if p.required and (p.name not in out or out[p.name] == "")]
        if missing:
            raise ToolError("آرگومان‌های لازم ارسال نشده: " + "، ".join(missing), BAD_ARGS)
        for p in tool.params:
            if p.name not in out and p.default is not None:
                out[p.name] = p.default
        return out

    # ---- execution ----
    def execute(self, name: str, args: Any, confirmed: bool = False) -> ToolResult:
        started = time.monotonic()
        tool = self.get(name)
        if tool is None:
            return ToolResult(str(name), UNKNOWN, f"ابزاری به نام «{name}» وجود ندارد. ابزارهای معتبر: {', '.join(self._tools)}.")

        def done(status, text, a=None, summary=""):
            return ToolResult(tool.name, status, clip(redact_secrets(text), tool.max_chars), a if a is not None else {}, tool.level,
                              int((time.monotonic() - started) * 1000), summary)

        try:
            clean = self.clean_args(tool, args)
            if tool.level >= SENSITIVE:
                if tool.precheck:
                    clean = tool.precheck(clean)                  # a denied / missing target is reported now, not after a question
                if not confirmed:
                    what = tool.confirm_summary(clean) if tool.confirm_summary else f"اجرای «{tool.name}»"
                    return done(NEEDS_CONFIRM, "این عملیات حساس است و هنوز اجرا نشده؛ منتظر تأیید صریح کاربر است: " + what, clean, what)
            if tool.intent_rx is not None and not tool.intent_rx.search(re.sub(r"\s+", " ", str(self.user_text or "").lower().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " "))):
                return done(DENIED, f"«{tool.name}» فقط در پاسخ به درخواست صریح کاربر در همین پیام اجرا می‌شود و چیزی تغییر نکرد. اگر کاربر واقعاً این را خواسته، از او بخواه صریح بنویسد (مثلاً «بلوتوث رو روشن کن»).", clean)
            text = tool.handler(clean)
            return done(OK, str(text if text is not None else "انجام شد."), clean)
        except ToolError as exc:
            return done(exc.status, str(exc), args if isinstance(args, dict) else {})
        except PermissionError as exc:
            return done(DENIED, f"ویندوز اجازه‌ی این کار را نداد: {exc}", args if isinstance(args, dict) else {})
        except FileNotFoundError as exc:
            return done(ERROR, f"پیدا نشد: {exc}", args if isinstance(args, dict) else {})
        except OSError as exc:
            return done(ERROR, f"خطای سیستم‌عامل: {exc}", args if isinstance(args, dict) else {})
        except Exception as exc:                                    # noqa: BLE001 - a tool may never crash the chat; the REAL error goes back
            return done(ERROR, f"خطای پیش‌بینی‌نشده در ابزار: {type(exc).__name__}: {exc}", args if isinstance(args, dict) else {})
