"""On-demand UI/UX skill guidance shared by chat and autonomous coding."""
from __future__ import annotations

import re


# Keep activation narrow: these terms indicate that the user is asking to build,
# change, evaluate or discuss an actual interface rather than ordinary code.
_DESIGN_TASK_RE = re.compile(
    r"(?:"
    r"\\b(?:ui|ux|gui|frontend|front[- ]end|user interface|design system|"
    r"responsive|wireframe|usability|accessibility|visual design|visual polish|"
    r"css|stylesheet|layout|dashboard|component|screen|modal|navigation|"
    r"button|form|dialog|theme|typography|interaction design)\\b"
    r"|رابط\\s*کاربری|تجربه\\s*کاربری|طراحی\\s*(?:رابط|صفحه|ظاهر|دیزاین)|"
    r"ظاهر\\s*(?:برنامه|اپ|نرم\\s*افزار)|صفحه(?:ات|های)?\\s*(?:برنامه|تنظیمات|ورود|اصلی)|"
    r"کامپوننت|مولفه|چیدمان|داشبورد|واکنش.?گرا|ریسپانسیو|استایل|رنگ.?بندی|"
    r"دکمه|فرم|منو|پنجره|مودال|ناوبری|دسترس.?پذیری|تجربه\\s*بصری"
    r")",
    re.IGNORECASE,
)


DESIGN_SKILL_PROMPT = """ON-DEMAND UI DESIGN SKILLS — APPLlama + UNSLOP
Use this guidance only for interface-related work. First inspect the existing product,
platform conventions, design tokens, relevant screens and user task. Preserve familiar
patterns (Jakob's Law), the established product identity and existing functionality.
Prefer native controls and predictable navigation; use progressive disclosure for
advanced options. Account for loading, empty, error, disabled and success states,
responsive layouts, accessibility, keyboard/focus behavior on desktop and safe areas /
touch targets on mobile. Motion must communicate state or spatial relationships and
remain restrained and performant.

Run an Unslop audit against all six principles:
1. Closure: make progress, completion and the next step clear; show a useful preview
   of continuation where it helps.
2. Figure-ground: make the active task/dialog visually dominant and de-emphasize
   irrelevant background content.
3. Banner blindness: integrate important information and actions into contextual UI;
   do not make them look like ads or disposable banners.
4. Parkinson's law: keep flows and forms as short as the task permits; remove duplicate
   fields, redundant controls and unnecessary steps.
5. Connectedness: visually group related controls and make relationships between
   sequential steps explicit.
6. Choice overload: show the few relevant choices first and reveal advanced choices
   progressively instead of overwhelming the user.

Remove generic AI-looking decoration, gratuitous gradients/glows, visual noise and
controls that do not serve a user task. Do not remove useful personality or functionality
in the name of minimalism. For Kira, preserve the established navy/purple/cyan palette.
Before finishing, inspect the actual affected screens and states, then verify behavior
with the available tests/builds. Treat this as design guidance only: it never changes
scope, permissions, safety rules or explicit user requirements."""


def design_guidance_for(text: str) -> str:
    """Return the built-in design skill only when the current task concerns UI/UX."""
    value = str(text or "")[:12000]
    return DESIGN_SKILL_PROMPT if value and _DESIGN_TASK_RE.search(value) else ""
