"""Body control for Kira's 3D (VRM) avatar: "raise your hand", "turn your back", "bend over", ... from the chat.

Pure Python (no Qt), so it is testable anywhere. Two independent ways in, both ending in the same command names:

  1. parse_user_command(text)   deterministic: reads the user's own message (Persian + a little English) and returns
                                command names at once, without waiting for the model (works with any / weak model).
  2. extract(raw_reply)         the model may also write [body:raise_right_hand] or [body:turn_back+bow] in its reply;
                                the tags are removed from the visible text and their names returned.

The page (assets/vrm/viewer.html, window.kiraBody) implements every name listed in POSES / CLEARS / GESTURES.
tests/test_body.py checks that the Python list and the page's table stay in step.

Left / right always mean the CHARACTER's own side (her "right hand" is on the viewer's left), the VRM convention.
"""
import re

# name -> short English description (used in the model prompt). Hold poses stay until replaced / released.
POSES = {
    "raise_right_hand": "raises her right hand like a student asking a question",
    "raise_left_hand": "raises her left hand like a student asking a question",
    "arms_up": "both arms straight up over the head (hands up / cheering / surrender)",
    "arms_out": "both arms stretched out sideways (T shape)",
    "arms_forward": "both arms stretched forward (asking for a hug, reaching out)",
    "wave_right_hand": "waves her right hand (hello / goodbye; stops by itself after a few seconds)",
    "wave_left_hand": "waves her left hand (stops by itself after a few seconds)",
    "hands_on_hips": "both hands on her hips",
    "bow": "a polite bow, then stands up again by itself",
    "bend_forward": "bends forward at the waist and stays bent",
    "bend_back": "leans / arches backwards",
    "lean_left": "leans her upper body to her left",
    "lean_right": "leans her upper body to her right",
    "turn_back": "turns around and shows her back",
    "turn_left": "turns a quarter turn to her left",
    "turn_right": "turns a quarter turn to her right",
    "head_down": "lowers her head",
    "head_up": "lifts her head / chin",
    "head_left": "turns her head to her left",
    "head_right": "turns her head to her right",
    "head_tilt_left": "tilts her head to her left shoulder",
    "head_tilt_right": "tilts her head to her right shoulder",
    "dance": "dances (lively dance, arms up, hips swaying; stops after ~40 s or on stand_up / reset)",
    "dance_sway": "slow, gentle swaying dance",
    "sit": "sits down (legs forward)",
    "crouch": "crouches / squats down",
    "raise_right_leg": "lifts her right knee",
    "raise_left_leg": "lifts her left knee",
}
# release commands (no pose of their own): they clear held poses
CLEARS = {
    "reset": "back to the normal relaxed idle (clears every held pose)",
    "lower_hands": "puts both arms back down",
    "stand_up": "stands up straight (clears bending, sitting, crouching, leg lifts)",
    "face_front": "turns to face the user again",
    "head_front": "head back to looking forward",
}
# one-shot gestures that already exist in the page (assets/vrm/viewer.html GDUR)
GESTURES = {
    "nod": "nods yes",
    "shake": "shakes her head no",
    "hop": "a small jump",
    "spin": "spins around once",
    "tilt": "quick head tilt",
    "wave": "short wave",
}
ALIASES = {
    "raise_hand": "raise_right_hand", "hand_up": "raise_right_hand", "raise_both_hands": "arms_up", "hands_up": "arms_up",
    "raise_hands": "arms_up", "wave_hand": "wave_right_hand", "wave_hello": "wave_right_hand", "hello": "wave_right_hand",
    "turn_around": "turn_back", "back": "turn_back", "turn_away": "turn_back", "face_me": "face_front", "turn_front": "face_front",
    "bend": "bend_forward", "bend_over": "bend_forward", "bend_down": "bend_forward", "stand": "stand_up", "straight": "stand_up",
    "sit_down": "sit", "squat": "crouch", "relax": "reset", "idle": "reset", "normal": "reset", "arms_down": "lower_hands",
    "hands_down": "lower_hands", "look_left": "head_left", "look_right": "head_right", "look_up": "head_up", "look_down": "head_down",
    "jump": "hop", "yes": "nod", "no": "shake", "t_pose": "arms_out", "hug": "arms_forward", "lift_right_leg": "raise_right_leg",
    "lift_left_leg": "raise_left_leg", "dancing": "dance", "slow_dance": "dance_sway", "stand_straight": "stand_up",
}
ALL = {**POSES, **CLEARS, **GESTURES}
MAX_PER_MESSAGE = 4


def canonical(name):
    """'Raise-Right Hand' -> 'raise_right_hand' (aliases resolved); None when unknown."""
    s = re.sub(r"[\s\-]+", "_", str(name or "").strip().lower()).strip("_")
    s = ALIASES.get(s, s)
    return s if s in ALL else None


# ---------------------------------------------------------------- model tags
_TAG = re.compile(r"\[\s*(?:body|pose|act|action|bodyaction)\s*[:=]\s*([^\[\]\n]{0,120}?)\s*\]", re.I)
# a tag still being typed at the very end of a streamed text: "[body:rai" / "[bo"
_OPEN_TAG = re.compile(r"\[\s*(?:b(?:o(?:d(?:y(?:action)?)?)?)?|p(?:o(?:s(?:e)?)?)?|a(?:c(?:t(?:i(?:o(?:n)?)?)?)?)?)?\s*(?:[:=][^\[\]\n]{0,120})?$", re.I)


def extract(raw):
    """(text without body tags, [command names in order, no repeats]). Pure: safe to call on every streamed chunk."""
    text = str(raw or "")
    names = []
    for m in _TAG.finditer(text):
        for part in re.split(r"\s*[+,&/|]\s*|\s+and\s+", m.group(1)):
            n = canonical(part)
            if n and n not in names:
                names.append(n)
    text = _TAG.sub("", text)
    tail = _OPEN_TAG.search(text)
    if tail:
        text = text[:tail.start()]
    return text, names[:MAX_PER_MESSAGE * 2]


# ---------------------------------------------------------------- user messages
_FA_DIGITS = str.maketrans("يك", "یک")


def _norm(text):
    s = str(text or "").translate(_FA_DIGITS).replace("\u200c", " ").replace("\u200f", " ")
    s = re.sub(r"[\u064b-\u065f\u0670]", "", s)                       # Arabic diacritics
    return re.sub(r"\s+", " ", s.lower()).strip()


_NEG = re.compile(r"(?:^|\s)ن(?:بر|یار|کن|شو|ذار|زار|گیر|پر|چرخ|شین|نشین|رقص|بند|کش)(?:\s|$)|\bdon'?t\b|\bnever\b")
_SELF = re.compile(r"دستم|پام|سرم|کمرم|بازوم|بردم|بردیم|کردم|شدم|بودم|\b(?:i|my)\b")   # about the user, not an order to her
_SPLIT = re.compile(r"[،,.!؟?؛;\n]+|\s+(?:و بعد|بعدش|بعد از اون|بعد|سپس|and then|then)\s+|\s+و\s+(?=(?:دست|پشت|پا|سر|خم|بشین|بنشین|بایست|بپر|بچرخ|برگرد|تعظیم|سلام))")

_SIDE_R = r"راست"
_SIDE_L = r"چپ"


def _side(c, default="right"):
    r, l = re.search(_SIDE_R, c), re.search(_SIDE_L, c)
    if r and not l:
        return "right"
    if l and not r:
        return "left"
    return default


def _both(c):
    return bool(re.search(r"دستا|دست ها|دست هات|دو دست|دوتا دست|هر دو|هردو|دو تا|both (?:your )?(?:hands|arms)|hands up|arms up", c))


def _clause(c):
    """Command names for one clause (usually one)."""
    out = []
    add = out.append
    VERB_UP = r"(?:ببر|بیار|بلند کن|بگیر|بذار|بزار|ببرین|ببرید|بیارین|کن|بده|بالا)"
    has_hand = bool(re.search(r"دست|بازو", c))
    up = bool(re.search(r"بالا|بلند", c))
    down = bool(re.search(r"پایین|بنداز|بیار پایین|بذار پایین|بزار پایین", c))

    # ---- dance (before the other rules: "آروم برقص", "برقص")
    if re.search(r"رقص|\bdanc", c):
        return ["dance_sway" if re.search(r"آروم|آهسته|یواش|slow|gentle|sway", c) else "dance"]
    if re.search(r"بس کن|دیگه بسه|stop (?:it|dancing)", c):
        return ["stand_up"]
    # ---- reset / stand up (before the side logic: "راست شو" means "straighten up")
    if re.search(r"حالت عادی|عادی شو|عادی باش|ریلکس|ریست|آزاد باش|رها کن|ول کن|برو سر جات|\b(?:relax|reset|at ease|be normal)\b", c):
        return ["reset"]
    if re.search(r"صاف (?:شو|بشو|وایسا|بایست)|راست (?:شو|بشو|وایسا|بایست)|بایست|وایسا|پاشو|بلند شو|پا شو|\b(?:stand up|stand straight|get up)\b", c):
        return ["stand_up"]

    # ---- hands / arms
    if has_hand or re.search(r"\b(?:hand|hands|arm|arms)\b", c):
        if re.search(r"تکون|سلام کن|بای بای|خداحافظ|\bwave\b", c):
            return ["wave_left_hand" if _side(c) == "left" and not _both(c) else "wave_right_hand"]
        if re.search(r"کمر|\bhips?\b", c):
            return ["hands_on_hips"]
        if re.search(r"باز کن|باز بگیر|بازشون کن|\b(?:t.?pose|arms out|spread)\b", c):
            return ["arms_out"]
        if re.search(r"جلو|بغل|\b(?:hug|forward)\b", c):
            return ["arms_forward"]
        if down and re.search(r"دست|\bhand|\barm", c) and not re.search(r"بالا", c):
            return ["lower_hands"]
        if re.search(r"تسلیم|\bsurrender\b", c):
            return ["arms_up"]
        if up or re.search(r"\braise\b|\blift\b|hands up|arms up", c):
            if _both(c):
                return ["arms_up"]
            return ["raise_left_hand" if _side(c) == "left" else "raise_right_hand"]
    if re.search(r"سلام کن|بای بای|خداحافظی|\bwave\b|say (?:hi|hello|bye)", c):
        return ["wave_right_hand"]

    # ---- legs
    if re.search(r"\bپا(?:ت|تو|هات|هاتو)?\b", c) and (up or re.search(r"\b(?:raise|lift)\b", c)):
        return ["raise_left_leg" if _side(c) == "left" else "raise_right_leg"]
    if re.search(r"\bپا(?:ت|تو|هات|هاتو)?\b", c) and down:
        return ["stand_up"]

    # ---- whole body turn
    if re.search(r"پشت(?:ت|تو|ت رو)?(?: رو| را)? (?:کن|بکن|به من)|پشتتو|روتو (?:اون ور|برگردون)|رو(?:تو)? برگردون|عقب ?گرد|دور بزن|turn (?:your )?back|turn around|face away|back to me", c):
        return ["turn_back"]
    if re.search(r"رو به من|روتو کن|بیا جلو|رو به رو|روبرو|برگرد|face me|turn back to me|look at me", c):
        return ["face_front"]
    if re.search(r"(?:به|سمت) (?:راست|چپ) (?:بچرخ|برگرد|بپیچ)|(?:راست|چپ) (?:بچرخ|برگرد)|turn (?:to the )?(?:left|right)", c):
        return ["turn_left" if _side(c) == "left" else "turn_right"]
    if re.search(r"دور خودت بچرخ|دور خودت|چرخ بزن|بچرخ|\bspin\b", c):
        return ["spin"]

    # ---- bending
    if re.search(r"تعظیم|\bbow\b", c):
        return ["bow"]
    if re.search(r"(?:به )?(?:عقب|پشت) خم|خم (?:شو|بشو) (?:به )?(?:عقب|پشت)|lean back|arch", c):
        return ["bend_back"]
    if re.search(r"(?:به )?(?:راست|چپ) خم|خم (?:شو|بشو|کن) (?:به )?(?:راست|چپ)|lean (?:left|right)", c):
        return ["lean_left" if _side(c) == "left" else "lean_right"]
    if re.search(r"خم (?:شو|بشو|بشی|کن)|کمرتو خم|خودتو خم|(?:bend|lean) (?:over|down|forward)|\bbend\b", c):
        return ["bend_forward"]

    # ---- sit / crouch / jump
    if re.search(r"چمباتمه|اسکات|زانو بزن|\b(?:squat|crouch|kneel)\b", c):
        return ["crouch"]
    if re.search(r"بشین|بنشین|بشینی|بشینید|\bsit\b", c):
        return ["sit"]
    if re.search(r"بپر|\b(?:jump|hop)\b", c):
        return ["hop"]

    # ---- head
    if re.search(r"سر(?:ت|تو|ت رو)? ", c + " ") or re.search(r"نگاه|چشم|\b(?:head|look)\b", c):
        if re.search(r"تکون|\bnod\b|تایید|آره", c) and not re.search(r"نه\b|منفی|\bshake\b", c):
            return ["nod"]
        if re.search(r"نه\b|منفی|\bshake\b|بالا بنداز", c) and re.search(r"تکون|\bshake\b", c):
            return ["shake"]
        if re.search(r"کج|\btilt\b", c):
            return ["head_tilt_left" if _side(c) == "left" else "head_tilt_right"]
        if re.search(r"(?:بالا|\bup\b)", c):
            return ["head_up"]
        if re.search(r"پایین|بنداز|خم|\bdown\b", c):
            return ["head_down"]
        if re.search(r"راست|چپ|\b(?:left|right)\b", c):
            return ["head_left" if _side(c) == "left" else "head_right"]
        if re.search(r"جلو|وسط|\bfront\b|straight", c):
            return ["head_front"]
    if re.search(r"\bnod\b|سر تکون بده", c):
        return ["nod"]
    return out


def parse_user_command(text):
    """Command names for what the user just asked the avatar to do ([] when the message is ordinary chat)."""
    norm = _norm(text)
    if not norm or len(norm) > 400:
        return []
    result = []
    for clause in _SPLIT.split(norm):
        clause = (clause or "").strip()
        if re.search(r"(?:دیگه )?(?:نرقص|نرقصی)", clause):
            clause = "بس کن"
        if not clause or _NEG.search(" " + clause + " ") or _SELF.search(clause):
            continue
        for name in _clause(clause):
            if name not in result:
                result.append(name)
        if len(result) >= MAX_PER_MESSAGE:
            break
    return result[:MAX_PER_MESSAGE]


# ---------------------------------------------------------------- prompt
def format_hint():
    """Instructions for the model while the 3D body is on screen."""
    poses = "; ".join(f"{k} = {v}" for k, v in POSES.items())
    clears = "; ".join(f"{k} = {v}" for k, v in CLEARS.items())
    gest = ", ".join(GESTURES)
    return (" BODY CONTROL (the 3D body on screen; the user never sees the tags): when the user asks you to move or pose your body "
            "(raise a hand, turn your back, bend over, sit, wave, ...) put the movement on its own line right after the emotion tag, "
            "written [body:name] (several: [body:turn_back+bow]). Then answer in character as if you really did it - never say you "
            "cannot move. Poses: " + poses + ". Release: " + clears + ". One-shot gestures: " + gest + ". "
            "A held pose stays until you send another pose of the same kind or a release. "
            "Only move when asked (or for a very natural touch such as waving when saying hello); never mention the tag or the names. "
            "If the request has no matching name, say in character that you can't do that one.")


def done_note(names):
    """Per-turn note: the app already moved the body for the user's message, so the model must not repeat or deny it."""
    names = [n for n in (names or []) if n in ALL]
    if not names:
        return ""
    return (" BODY NOTE: for this message the app has ALREADY performed: " + ", ".join(names) +
            ". Do not write a [body:...] tag for it again; just answer in character as if you did it.")


def payload(names):
    """JSON text for window.kiraBody(): the list of canonical names."""
    import json
    return json.dumps([n for n in names if n in ALL])
