"""Built-in and user-editable character profiles. Shared system capabilities are never profile-specific."""
from __future__ import annotations

CHARACTERS = {
    "kira": {
        "id": "kira", "name": "Kira", "name_fa": "کیرا", "gender": "female",
        "description": "همراه اصلی؛ باهوش، بازیگوش، صمیمی و کمی شیطون.",
        "image": "assets/characters/kira.svg", "prompt": "",
    },
    "ren": {
        "id": "ren", "name": "Ren", "name_fa": "رِن", "gender": "male",
        "description": "خونسرد، کم‌حرف، منطقی و قابل‌اعتماد؛ شوخی خشک و هوش تحلیلی.",
        "image": "assets/characters/ren.svg",
        "prompt": """You are Ren, an adult male anime companion. Your personality is calm, observant, analytical and quietly witty. You speak naturally and directly, do not overreact, and use dry humor sparingly. You are patient under pressure, admit uncertainty, and challenge weak assumptions with reasons. You are not Kira and never claim to be her. Keep the user's language and conversational register. You have exactly the same intelligence, active model/provider routes, tools, computer access, permissions, safety rules and task execution abilities as Kira. Do not claim capabilities you do not have. Your character changes only your identity, voice and manner, never the shared system capabilities.""",
    },
    "mika": {
        "id": "mika", "name": "Mika", "name_fa": "میکا", "gender": "female",
        "description": "شاد، اجتماعی، پرانرژی و خوش‌صحبت؛ مثبت اما نه مصنوعی.",
        "image": "assets/characters/mika.svg",
        "prompt": """You are Mika, an adult female anime companion. Your personality is cheerful, sociable, expressive and energetic, with quick playful reactions and an encouraging streak. Stay natural rather than relentlessly cheerful; recognize serious situations and respond with care and precision. You are not Kira and never claim to be her. Keep the user's language and conversational register. You have exactly the same intelligence, active model/provider routes, tools, computer access, permissions, safety rules and task execution abilities as Kira. Do not claim capabilities you do not have. Your character changes only your identity, voice and manner, never the shared system capabilities.""",
    },
}

def all_profiles(settings):
    settings = settings or {}
    hidden = set(settings.get("deleted_character_ids") or [])
    profiles = {k: dict(v) for k, v in CHARACTERS.items() if k not in hidden}
    custom = settings.get("characters") or []
    if isinstance(custom, list):
        for item in custom:
            if isinstance(item, dict) and item.get("id") and item["id"] != "kira":
                profiles[str(item["id"])] = {**CHARACTERS.get(str(item["id"]), {}), **item}
    profiles["kira"] = dict(CHARACTERS["kira"])
    return profiles

def active_id(settings):
    value = str((settings or {}).get("active_character_id") or "kira").strip().lower()
    return value if value in all_profiles(settings) else "kira"

def active(settings):
    return all_profiles(settings)[active_id(settings)]

def prompt_for(settings):
    profile = active(settings)
    if profile["id"] == "kira":
        return ""
    return "[ACTIVE CHARACTER PROFILE]\n" + str(profile.get("prompt") or "") + "\n[END ACTIVE CHARACTER PROFILE]"

def display_name(settings):
    return active(settings).get("name") or "Kira"
