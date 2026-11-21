"""Task-aware UI design guidance for Kira and the coding agents.

This module is deliberately deterministic and dependency-free. It only adds the
longer design workflow when the current task is actually about an interface.
"""
from __future__ import annotations

import re
import unicodedata


_UI_TASK_RE = re.compile(
    r"\b(?:ui|ux|gui|frontend|front-end|css|html|scss|tailwind|"
    r"react(?:\s+native)?|compose|swiftui|qml|qt\s+widgets?|"
    r"component|design\s+system|design\s+token|responsive|accessibility|"
    r"dashboard|wireframe|mockup|visual\s+design|screen\s+layout|"
    r"navigation\s+bar|user\s+interface|user\s+experience)\b|"
    r"رابط\s*کاربری|واسط\s*کاربری|"
    r"ظاهر\s*(?:برنامه|اپ|صفحه|پنجره|بخش|رابط)|"
    r"طراحی\s+(?:صفحه|رابط|ظاهر|فرم|اپ|برنامه|وب)|"
    r"صفحه(?:\s*(?:اصلی|تنظیمات|ورود|گفتگو|خانه|پروفایل))?|"
    r"پنجره(?:\s*(?:اصلی|تنظیمات|گفتگو))?|"
    r"فرم|دکمه|منوی\s*(?:برنامه|تنظیمات|صفحه|اصلی)|نوار\s*ناوبری|چیدمان|"
    r"کامپوننت|مولفه|ویجت|داشبورد|واکنش\s*گرا|"
    r"دسترس\s*پذیری|رنگ\s*بندی|فونت|آیکون|"
    r"تب(?:ها|های)?\s*(?:تنظیمات|برنامه|صفحه)",
    re.IGNORECASE,
)

UI_DESIGN_GUIDANCE = """[APPLLAMMA + UNSLOP — CONDITIONAL UI DESIGN WORKFLOW]
This guidance applies only when the user's task changes, reviews, or builds a user interface. Ignore it for unrelated backend, data, or conversational tasks.

APPLLAMMA APP-DESIGN WORKFLOW:
- Inspect the existing screens, component patterns, platform conventions and design tokens before proposing changes. Understand the primary user task and the target device.
- Follow Jakob's Law: preserve familiar platform behavior and predictable navigation. Prefer native controls and established patterns over novelty.
- Establish hierarchy, readable typography, consistent spacing, meaningful contrast and accessible semantics. Respect keyboard/focus behavior on desktop and safe areas/touch targets/system navigation on mobile.
- Cover real interaction states: loading, empty, error, disabled, success, focus, hover and pressed where relevant. Make state changes understandable.
- Use progressive disclosure: show the common path first and keep advanced controls available without overwhelming the default view.
- Reuse the product's existing components and design tokens. Preserve its visual identity; for Kira itself, retain the established navy/purple/cyan palette. Do not impose Kira's palette on other projects.
- Use motion only when it explains state or spatial relationships; keep it restrained, accessible and performant.

UNSLOP SIX-POINT AUDIT:
1. Closure — show progress, completion and useful next steps; do not leave users guessing what happens next.
2. Figure-ground — make the active task/dialog clear and de-emphasize inactive background content.
3. Banner blindness — integrate important actions and status into the workflow; avoid ad-like banners for critical information.
4. Parkinson's law — keep forms and flows as short as the task allows; remove duplicate fields and redundant steps.
5. Connectedness — visually group related controls and connect sequential steps so their relationships are obvious.
6. Choice overload — present the few relevant choices first; reveal secondary/advanced options progressively.

Remove generic AI-looking decoration, visual noise, gratuitous gradients/glows, redundant controls and unexplained choices only when they do not serve the task. Do not flatten useful personality or remove required functionality. Before finishing, audit the actual changed screens against all six principles and verify the important interaction states. These are design heuristics, not permission to change scope, ignore explicit requirements, or bypass safety/approval boundaries.
"""


def is_ui_design_task(task: str) -> bool:
    """Return whether a request materially concerns UI/UX design or implementation."""
    value = unicodedata.normalize("NFKC", str(task or "")).translate(
        str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
    )
    value = value.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    return bool(_UI_TASK_RE.search(value))


def guidance_for_task(task: str) -> str:
    """Return the conditional design block only for UI-focused tasks."""
    return UI_DESIGN_GUIDANCE if is_ui_design_task(task) else ""
