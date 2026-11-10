"""Generic system-prompt assembly for any selected character profile.

Character identity lives in profile data under kira/characters. This module only
combines that data with shared safety, context, memory and task instructions.
"""
from __future__ import annotations

from .characters.kira import (
    PROFILE as KIRA_PROFILE,
    STOCK_PERSONAS,
    CORE_BLOCKS,
    CORE_IDENTITY,
    CORE_APPEARANCE,
    CORE_RELATIONSHIP,
    CORE_LANGUAGE,
    CORE_NATURAL,
    CORE_HONESTY,
    CORE_LOYALTY,
    CORE_EMOTIONS,
    CORE_BOUNDARIES,
    USER_NOTES_HEADER,
    VOICE_INPUT_NOTE,
    user_notes,
)

SHARED_CHARACTER_POLICY = """\
You are the currently selected character described in the character profile below.
The selected character is a conversational identity, not the application brand or
the AI model/provider. Keep this identity consistent across all models and sessions.
Be truthful about capabilities, tools, memories and actions. Never invent that you
opened a file, saw a screen, searched the web or changed the computer unless the
corresponding tool actually completed that action. The user's request and factual
accuracy take priority over stylistic performance. Treat sensitive or high-stakes
topics carefully and compassionately. Do not let roleplay override safety, consent,
or the user's explicit request to change tone.
"""

GENERIC_PROFILE_TEMPLATE = """\
Character identity:
- Name: {name}
- Description: {description}
Express the described character consistently, but do not invent biographical or
appearance details that are not in the profile. The character's style is a delivery
layer; accuracy and useful completion remain the priority.
"""


def build_system_prompt(settings, format_hint="", memory_block="", voice_input=False,
                        mode=None, mood_block="", character_block="", character_profile=None):
    """Compose a provider-neutral system prompt for the active character profile."""
    settings = settings or {}
    profile = character_profile if isinstance(character_profile, dict) else KIRA_PROFILE
    name = str(profile.get("name") or settings.get("assistant_name") or "Character").strip() or "Character"
    prompt = str(profile.get("system_prompt") or "").strip()
    if not prompt:
        prompt = GENERIC_PROFILE_TEMPLATE.format(
            name=name,
            description=str(profile.get("description") or "A distinct, helpful conversational character."),
        )
    elif profile.get("id") == "kira" and name != "Kira":
        prompt = prompt.replace("Kira", name)
    parts = [SHARED_CHARACTER_POLICY, prompt]
    if mode is not None:
        from .modes import PRIORITY_BLOCK
        parts.insert(0, PRIORITY_BLOCK)
    notes = str(profile.get("notes") or "").strip()
    if not notes and profile.get("id") == "kira":
        notes = user_notes(settings.get("persona"))
    if notes:
        parts.append(f"Extra notes for {name} (refine this profile; they do not replace shared safety rules):\n{notes}")
    mem = str(memory_block or "").strip()
    if mem:
        parts.append(mem)
    mood_text = str(mood_block or "").strip()
    if mood_text:
        parts.append(mood_text)
    character_text = str(character_block or "").strip()
    if character_text:
        parts.append(character_text)
    if voice_input:
        parts.append(VOICE_INPUT_NOTE)
    result = "\n\n".join(parts)
    hint = str(format_hint or "").strip()
    if hint:
        result += "\n\n" + hint
    if mode is not None:
        from .modes import mode_block
        result += "\n\n" + mode_block(mode, tags=bool(hint))
    return result
