"""Windows Control Layer: how a Windows capability (apps, Bluetooth, audio, desktop, later wallpaper / tray / system / Office) is DECLARED.

It does not decide permissions any more: that is the job of the Unified System Access Manager (sysaccess.py), which every tool passes through
inside ToolRegistry.execute(). A module only states what its operation is, and this layer turns the declaration into an ordinary registry Tool:

  * a fixed name, a fixed handler and a closed list of typed parameters. Parameters that look like a free command line / script are refused.
  * `permission`: READ / CONTROL / FILE / ELEVATED / PROTECTED (sysaccess). When it is not given it follows `risk`:
        READ -> READ, ACTION -> CONTROL, SENSITIVE -> PROTECTED.
  * CONTROL / FILE must either require the user's explicit request in the CURRENT message (`intent_rx`) or state why not (`intent_optout`).
  * ELEVATED / PROTECTED must describe in plain words what will happen (`confirm_summary`); the manager then asks the user first.
  * `backend` (+ optional `fallbacks`): which code really does the work. A backend that raises BackendUnavailable hands over to the next one.
  * the handler reports the real result (text) or raises ToolError with the real reason; the manager journals every outcome.

Adding a feature: write a WinModule with a `domain` and `capabilities()` and register it in builtin.py. See docs/SYSTEM_ACCESS_FA.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .registry import ToolRegistry, Tool, ToolError, Param, READ, ACTION, SENSITIVE, LEVEL_NAMES
from .sysaccess import (BACKENDS, BackendUnavailable, PERMISSION_NAMES, READ_P, CONTROL, FILE, ELEVATED, PROTECTED)

# Every domain the layer knows. A future feature = one new line here + one module.
DOMAINS = {"apps": "اجرای برنامه‌ها", "bluetooth": "بلوتوث", "audio": "صدا", "wallpaper": "والپیپر", "tray": "System Tray", "system": "مدیریت سیستم", "desktop": "تعامل با دسکتاپ"}
FORBIDDEN_PARAM_NAMES = {"command", "cmd", "commandline", "command_line", "script", "shell", "powershell", "bash", "exec", "code", "expression", "argv"}


@dataclass
class Capability:
    name: str                                   # tool name the model uses
    domain: str                                 # key of DOMAINS
    description: str                            # one line shown to the model
    handler: Callable[[dict], str]
    risk: int = READ                            # READ | ACTION | SENSITIVE
    params: tuple = ()                          # tuple[Param]
    categories: tuple = ()                      # request-intent categories (protocol.GATES) that make the tool visible
    intent_rx: Any = None                       # ACTION: regex the user's CURRENT message must match (explicit request)
    intent_optout: str = ""                     # ACTION without intent_rx: the reason (documented, shown in the capability table)
    confirm_summary: Callable[[dict], str] | None = None
    precheck: Callable[[dict], dict] | None = None
    memo: Callable[[dict, str], str | None] | None = None
    max_chars: int | None = None
    verifies_result: bool = False               # True: the handler re-reads the real state after changing it
    changes_system: bool = False                # informational: does it change anything outside Kira?
    permission: int = 0                         # sysaccess level; 0 = derive from `risk`
    backend: str = ""                           # sysaccess.BACKENDS key; "" = the domain's default
    fallbacks: tuple = ()                       # ((backend name, handler), ...) tried in order when the previous backend raises BackendUnavailable
    external: bool = False                      # the RESULT is content written by somebody else (taints the turn)


class WinModule:
    """Base class of a Windows feature. Subclasses set `domain` and return their capabilities."""
    domain: str = ""

    def capabilities(self) -> list[Capability]:
        raise NotImplementedError


DOMAIN_BACKEND = {"apps": "win32", "bluetooth": "powershell-fixed", "audio": "com", "wallpaper": "win32", "tray": "win32", "system": "win32", "desktop": "win32"}


class WindowsControlLayer:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._caps: dict[str, Capability] = {}

    # ------------------------------------------------------------ registration
    def register_module(self, module: WinModule) -> None:
        for cap in module.capabilities():
            if cap.domain != module.domain:
                raise ValueError(f"قابلیت «{cap.name}» به دامنه‌ی «{cap.domain}» اعلام شده ولی ماژول «{module.domain}» است.")
            self.register(cap)

    @staticmethod
    def _permission(cap: Capability) -> int:
        if cap.permission:
            return cap.permission
        return {READ: READ_P, ACTION: CONTROL, SENSITIVE: PROTECTED}[cap.risk]

    def register(self, cap: Capability) -> Tool:
        self._validate(cap)
        perm = self._permission(cap)
        self._caps[cap.name] = cap
        # the legacy registry level follows the permission: only READ / (CONTROL, FILE) / (ELEVATED, PROTECTED) exist there
        level = READ if perm == READ_P else ACTION if perm in (CONTROL, FILE) else SENSITIVE
        kwargs = {"max_chars": cap.max_chars} if cap.max_chars else {}
        return self.registry.register(Tool(cap.name, cap.description, self._wrap(cap), tuple(cap.params), level, tuple(cap.categories),
                                           confirm_summary=cap.confirm_summary, precheck=cap.precheck, memo=cap.memo, intent_rx=cap.intent_rx,
                                           permission=perm, domain=cap.domain, backend=cap.backend or DOMAIN_BACKEND[cap.domain],
                                           verifies_result=cap.verifies_result, external=cap.external, **kwargs))

    @staticmethod
    def _validate(cap: Capability) -> None:
        if cap.domain not in DOMAINS:
            raise ValueError(f"دامنه‌ی «{cap.domain}» برای «{cap.name}» تعریف نشده (دامنه‌های مجاز: {', '.join(DOMAINS)}).")
        if cap.risk not in LEVEL_NAMES:
            raise ValueError(f"سطح ریسک «{cap.name}» معتبر نیست.")
        if cap.permission and cap.permission not in PERMISSION_NAMES:
            raise ValueError(f"permission «{cap.name}» معتبر نیست.")
        if cap.backend and cap.backend not in BACKENDS or any(b not in BACKENDS for b, _ in cap.fallbacks):
            raise ValueError(f"backend «{cap.name}» ناشناخته است (مجاز: {', '.join(BACKENDS)}).")
        if not cap.categories:
            raise ValueError(f"«{cap.name}» باید حداقل یک دسته‌ی نمایش (categories) داشته باشد.")
        for p in cap.params:
            if p.name.lower() in FORBIDDEN_PARAM_NAMES:
                raise ValueError(f"پارامتر «{p.name}» در «{cap.name}» مجاز نیست: دستور آزاد/اسکریپت ورودی ابزار نمی‌شود.")
        perm = WindowsControlLayer._permission(cap)
        if perm in (CONTROL, FILE) and cap.intent_rx is None and not cap.intent_optout:
            raise ValueError(f"«{cap.name}» کنترل/فایل است: یا intent_rx (درخواست صریح کاربر) بدهید یا دلیل intent_optout را بنویسید.")
        if perm >= ELEVATED and cap.confirm_summary is None:
            raise ValueError(f"«{cap.name}» سطح {PERMISSION_NAMES[perm]} است و باید confirm_summary داشته باشد.")
        if perm == READ_P and cap.changes_system:
            raise ValueError(f"«{cap.name}» READ است ولی changes_system=True دارد.")

    # ------------------------------------------------------------ backend chain
    def _wrap(self, cap: Capability):
        access = self.registry.access
        chain = [(cap.backend or DOMAIN_BACKEND[cap.domain], cap.handler)] + list(cap.fallbacks)

        def run(args: dict) -> str:
            skipped = []
            for name, fn in chain:
                try:
                    text = fn(args)
                except BackendUnavailable as exc:
                    skipped.append(f"{BACKENDS.get(name, name)}: {exc}")
                    continue
                access.set_backend(name)
                return text
            raise ToolError("هیچ‌کدام از روش‌های اجرا در این سیستم در دسترس نبود: " + " | ".join(skipped))
        return run

    # ------------------------------------------------------------ introspection
    def capabilities(self) -> list[Capability]:
        return list(self._caps.values())

    def register_info_tool(self) -> None:
        """The manager's own read-only report: every tool with its level, backend and gate, plus the real recent operations / errors."""
        self.registry.register(Tool("windows_control_info", "list every tool with its permission level, backend and safety gate, and the real recent operations / errors",
                                    lambda a: self.registry.access.info_text(), (), READ, ("system",), permission=READ_P, domain="system", backend="python"))
