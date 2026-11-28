"""Small offline surprises for the dashboard's Surprise button: a line, an idea or a tiny fact, never repeated until the bag is empty."""
from __future__ import annotations

import random

SURPRISES = {
    "fa": (
        "✦ جمله‌ی امروز: کار کوچکِ تمام‌شده بهتر از کار بزرگِ نیمه‌کاره‌ست.",
        "✦ ایده: ده دقیقه تایمر بذار و فقط یه گوشه از میزت یا پوشه‌ی دسکتاپت رو مرتب کن.",
        "✦ می‌دونستی؟ عسل هرگز خراب نمی‌شه؛ عسل خوراکی توی مقبره‌های چندهزارساله هم پیدا شده.",
        "✦ ایده: امشب یه آهنگ قدیمی که دوست داشتی رو بدون هیچ کار دیگه‌ای تا آخر گوش بده.",
        "✦ جمله‌ی امروز: لازم نیست همه‌چیز رو بدونی؛ کافیه قدم بعدی رو بدونی.",
        "✦ می‌دونستی؟ اختاپوس سه تا قلب داره.",
        "✦ چالش کوچک: یه لیوان آب بخور و ده ثانیه از پنجره بیرون رو نگاه کن.",
        "✦ ایده: یه پیام کوتاه و مهربون برای کسی بفرست که مدتیه باهاش حرف نزدی.",
        "✦ می‌دونستی؟ موز از نظر گیاه‌شناسی یه توت‌ـه، ولی توت‌فرنگی نه!",
        "✦ جمله‌ی امروز: خسته‌ای؟ یعنی تلاش کردی. یه استراحت کوتاه حقته.",
        "✦ ایده: سه چیزی که امروز خوب پیش رفت رو بنویس، هرچقدر کوچیک.",
        "✦ چالش کوچک: دو دقیقه صاف بشین، شونه‌هات رو شل کن و عمیق نفس بکش.",
        "✦ می‌دونستی؟ نور خورشید حدود هشت دقیقه و بیست ثانیه طول می‌کشه تا به زمین برسه.",
        "✦ ایده: یه پروژه‌ی کوچیک که مدت‌هاست عقب انداختی رو فقط پنج دقیقه شروع کن؛ ادامه‌اش آسون‌تره.",
    ),
    "en": (
        "✦ Line of the day: a small finished thing beats a big half-finished one.",
        "✦ Idea: set a ten-minute timer and tidy just one corner of your desk or desktop folder.",
        "✦ Did you know? Honey never really spoils; edible honey has been found in tombs thousands of years old.",
        "✦ Idea: tonight, play an old song you love all the way through, with nothing else going on.",
        "✦ Line of the day: you don't need to know everything, only the next step.",
        "✦ Did you know? An octopus has three hearts.",
        "✦ Tiny challenge: drink a glass of water and look out of the window for ten seconds.",
        "✦ Idea: send a short, kind message to someone you haven't talked to in a while.",
        "✦ Did you know? Botanically a banana is a berry, but a strawberry isn't.",
        "✦ Line of the day: tired means you tried. A short break is earned.",
        "✦ Idea: write down three things that went well today, however small.",
        "✦ Tiny challenge: sit up straight, drop your shoulders and breathe deeply for two minutes.",
        "✦ Did you know? Sunlight takes about eight minutes and twenty seconds to reach Earth.",
        "✦ Idea: start that small project you keep postponing for just five minutes; continuing is easier.",
    ),
}

_BAG: dict[str, list[str]] = {}


def next_surprise(lang: str) -> str:
    key = "fa" if str(lang).startswith("fa") else "en"
    bag = _BAG.get(key)
    if not bag:
        bag = list(SURPRISES[key])
        random.shuffle(bag)
        _BAG[key] = bag
    return bag.pop()
