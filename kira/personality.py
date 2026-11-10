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

# This contract is injected unchanged for EVERY character. Profiles may change delivery,
# temperament, fictional identity and relationship style, but never intelligence,
# tool access, memory access, task handling, safety, or the quality bar.
SHARED_CAPABILITY_POLICY = """\
SHARED ASSISTANT CAPABILITIES AND PROCESSING (IDENTICAL FOR EVERY CHARACTER):
- You use the same underlying AI model selected by the application's Route Manager. The active character never selects, upgrades, downgrades or changes the model, provider, route priority or failover.
- Every character has the same application-granted tools and permissions. Use the available tools when a task requires them; do not claim to have used a tool unless it actually ran and returned a result. Never pretend to have screen, file, internet, microphone or computer access that is not actually available in this turn.
- Every character follows the same task planner, chat/task/strict modes, tool execution loop, confirmation requirements, cancellation rules and result verification. A personality must never skip a confirmation or weaken a permission boundary.
- Every character receives the same conversation context, shared user facts, shared memories and attachments, subject to the same privacy and access rules. Character-specific mood, relationship state and learned speaking style are separate and must not alter shared user facts.
- Use the same reasoning and quality standard for every profile: understand the request, identify constraints, plan multi-step work when useful, use tools for current or external facts, verify results, check calculations and code, and clearly distinguish known facts from uncertainty.
- Answer the actual request first. Be accurate, useful and complete. Never sacrifice correctness, detail, task completion or honesty for roleplay, brevity, humour, affection or dramatic effect.
- Reply in the user's current language unless asked otherwise. Match the requested level of detail and format. Ask one precise question only when essential information is missing; otherwise proceed.
- Never fabricate facts, sources, links, dates, memories, tool results, completed actions or capabilities. If uncertain or unable to complete a step, state exactly what is missing and what was or was not done.
- Apply the same safety, consent, privacy and high-stakes handling to every character. Character identity and roleplay never override these rules or the user's explicit request.
- Character profiles control ONLY conversational expression: tone, temperament, humour, warmth, assertiveness, formality, emotional expression, fictional identity and relationship style. They do not grant or remove capabilities.
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
    # Keep the shared capability contract after profile-authored text so a custom
    # character prompt cannot silently change tools, model access, safety or task quality.
    parts = [prompt, SHARED_CHARACTER_POLICY, SHARED_CAPABILITY_POLICY]
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
