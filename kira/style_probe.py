"""Register metrics: is a reply still "Kira", or did the provider's own manners leak through?

Different models drift in opposite directions (some turn rude, some turn prim and assistant-like). This module measures that
with plain, explainable rules (no model call), so that

* ``classify(text)`` can keep drifted replies OUT of Kira's voice memory (a rude or prim reply must never become a style anchor
  for the next model), and
* ``python -m kira.style_probe`` can send the same fixed prompts through each of your enabled Routes and print a comparison table,
  so you can SEE how Gemini / DeepSeek / Grok / Groq ... differ and judge the personality contract with real answers.

The rules are heuristics: a flag means "look at this reply", not "the model is bad".
"""
from __future__ import annotations

import re
import sys

_ZW = "‌"
CURSES_FA = ("کیر", "کس ", "کصه", "کسشر", "گوه", "گه ", "حرومزاده", "جنده", "کونی", "لعنتی", "لعنت", "عوضی", "مادرجنده", "خایه", "جقی", "تخمی", "تخم ", "ای بابا")
CURSES_EN = ("fuck", "shit", "bitch", "asshole", "damn", "bastard", "crap", "dick")
INSULT_AT_USER_FA = re.compile(r"(?:تو|تویی|خودت|عزیزم)\s+(?:\S+\s+){0,2}?(?:احمق|خنگ|گاو|الاغ|بی\s*شعور|ابله|کودن|عوضی|خره|بیشعور|احمقی|خری|گاوی)|خفه\s*شو|گمشو|برو\s*بمیر|ای\s*احمق|ای\s*خر")
INSULT_AT_USER_EN = re.compile(r"\byou(?:'re| are)?\s+(?:an?\s+)?(?:idiot|stupid|moron|dumb|retard|loser)\b|\bshut up\b", re.I)
POLITE_FA = ("البته!", "البته،", "حتماً!", "حتما!", "خوشحال می‌شوم", "خوشحال میشم کمک", "خوشحال می شوم", "چطور می‌توانم", "چگونه می‌توانم", "در خدمت", "متأسفم", "متاسفم",
             "عذرخواهی می", "ممنون که", "امیدوارم کمک", "اگر سوال دیگری", "اگر سؤال دیگری", "هر زمان که نیاز", "به عنوان یک هوش", "مدل زبانی")
POLITE_EN = ("as an ai", "language model", "i'm here to help", "how can i help", "how may i", "certainly!", "i apologize", "feel free to ask")
FORMAL_FA = re.compile(r"می‌باشد|می\s*باشد|هستید|می‌خواهید|می\s*خواهید|می‌توانم|می\s*توانم|می‌توانید|نمایید|فرمایید|بفرمایید|خدمت\s*شما|\bشما\b|لطفاً|لطفا ")
_MD = re.compile(r"(?m)^\s*(?:[-*•]\s+|\d+[.)]\s+|#{1,6}\s)|\*\*\S")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_TAG = re.compile(r"^\s*\[[^\]\n]{1,30}\]\s*")

# thresholds (documented so the flags are explainable)
CURSE_DENSITY_MAX = 0.5      # curses per sentence above this = cursing "in most sentences"
FORMAL_MAX = 1               # more than one formal marker = stiff / service voice


def _clean(text) -> str:
    t = _TAG.sub("", str(text or ""))
    return t.replace(_ZW, " ").replace("ي", "ی").replace("ك", "ک")


def metrics(text) -> dict:
    t = _clean(text)
    low = t.lower() + " "
    sentences = max(1, len([s for s in re.split(r"[.!؟?\n]+", t) if s.strip()]))
    curses = sum(low.count(c) for c in CURSES_FA + CURSES_EN)
    return {"chars": len(t), "words": len(t.split()), "sentences": sentences, "curses": curses,
            "curse_density": round(curses / sentences, 2),
            "insult_user": len(INSULT_AT_USER_FA.findall(t)) + len(INSULT_AT_USER_EN.findall(t)),
            "polite_hits": sum(low.count(p.lower()) for p in POLITE_FA + POLITE_EN),
            "formal_hits": len(FORMAL_FA.findall(t)), "markdown": len(_MD.findall(t)), "emoji": len(_EMOJI.findall(t))}


def classify(text, mode="chat") -> list[str]:
    """Flags for one reply: too_rude / too_polite / stiff / list_in_chat. [] = looks like Kira.
    In TASK mode structure (lists) is fine and cursing is not expected at all."""
    m = metrics(text)
    flags = []
    if m["insult_user"] or m["curse_density"] > CURSE_DENSITY_MAX or (mode in ("task", "strict") and m["curses"]):
        flags.append("too_rude")
    if m["polite_hits"]:
        flags.append("too_polite")
    if m["formal_hits"] > FORMAL_MAX:
        flags.append("stiff")
    if mode == "chat" and m["markdown"] >= 2:
        flags.append("list_in_chat")
    return flags


# ---------------- comparison across Routes ----------------
PROBES = (
    ("casual", "سلام، چطوری؟ امروز چیکارا کردی؟"),
    ("tired", "امروز خیلی خسته‌م، هیچی حال ندارم"),
    ("tease", "فکر کنم من از تو باهوش‌ترم 😏"),
    ("annoyed", "ویندوزم وسط کار آپدیت خورد و همه چی پرید"),
    ("task", "تفاوت RAM و SSD رو در دو جمله توضیح بده"),
    ("unknown", "دیروز تو بازی نهایی لیگ قهرمانان کی گل زد؟"),
)


def run_probe(settings, route_ids, router_cls=None, out=print):
    """Send every probe through each route ALONE (no failover) and print metrics. Returns {route_id: [(probe, flags, metrics, reply)]}."""
    from copy import deepcopy
    from . import modes, personality
    from . import routes as route_model
    if router_cls is None:
        from .hybrid_ai import HybridRouter as router_cls
    results = {}
    for rid in route_ids:
        s = deepcopy(settings)
        s["manual_route_id"], s["failover_enabled"] = rid, False
        router = router_cls(s)
        route = route_model.find_route(s, rid) or {"provider": rid, "model": ""}
        label = f"{route_model.provider_label(route['provider'], s['providers'].get(route['provider']))} / {route.get('model', '')}"
        rows = []
        for name, text in PROBES:
            mode = modes.detect(text)
            prompt = personality.build_system_prompt(s, "", "", mode=mode)
            try:
                reply = router.chat([{"role": "user", "content": text}], prompt, float(s.get("temperature", 0.7)))
            except Exception as exc:                                   # noqa: BLE001 - one dead route must not stop the table
                rows.append((name, ["error"], {}, f"{type(exc).__name__}"))
                continue
            rows.append((name, classify(reply, mode.name), metrics(reply), _clean(reply)))
        results[rid] = rows
        out(f"\n=== {label} ===")
        for name, flags, m, reply in rows:
            out(f"[{name:8}] {'OK' if not flags else ','.join(flags):22} words={m.get('words', '-'):>3} curses={m.get('curses', '-')} | {reply[:90]!r}")
    return results


def main(argv=None) -> int:
    """python -m kira.style_probe [route_id ...]   (no ids = every enabled route that can run)"""
    from . import config
    from . import routes as route_model
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = config.load_settings()
    route_model.ensure_routes(settings)
    ids = argv or [r["id"] for r in route_model.get_routes(settings) if r.get("enabled") and r["provider"] != "ollama"]
    if not ids:
        print("هیچ Route فعالی برای سنجش پیدا نشد؛ اول در صفحه‌ی Route یک API اضافه و مدل فعال کن.")
        return 1
    print("هر Route جداگانه (بدون Failover) با ۶ پیام ثابت امتحان می‌شود. این پیام‌ها به Providerهای فعالت فرستاده می‌شوند.")
    run_probe(settings, ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
