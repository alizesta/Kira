"""Windows Control modules. Each module only DECLARES its capabilities (name, risk, gate); the working code stays where it was
(apps.py, appcatalog.py, bluetooth.py, audio.py). Permissions, confirmation and the journal are NOT decided here: sysaccess.py enforces what is declared. To add Wallpaper / Tray / System Manager: add a WinModule here (or in its own file) and
register it in builtin.py."""
from __future__ import annotations

import re

from .apps import AppTools
from .audio import AudioTools
from .bluetooth import BluetoothTools
from .registry import Param, READ, ACTION
from .wincontrol import Capability, WinModule

_BT_WORD = r"(?:بلو\s*توث|بلو\s*توس|bluetooth)"
BT_ON_RX = re.compile(_BT_WORD + r".*(?:روشن|فعال|وصل|بزن|\bon\b|enable|turn\s*on|switch\s*on|start)|(?:روشن|فعال|turn\s*on|switch\s*on|enable)\s*.*" + _BT_WORD, re.I)
BT_OFF_RX = re.compile(_BT_WORD + r".*(?:خاموش|غیر\s*فعال|قطع|\boff\b|disable|turn\s*off|switch\s*off|stop)|(?:خاموش|غیر\s*فعال|قطع|turn\s*off|switch\s*off|disable)\s*.*" + _BT_WORD, re.I)

# ---- Audio: the user's CURRENT message must contain an explicit request for the change (checked by the layer before the handler runs) ----
def _pv(*words: str) -> str:
    """Persian/English verb alternatives with word boundaries (Persian has no spaces inside a word, so a bare 'کن' would match 'کنترل')."""
    return r"\b(?:" + "|".join(words) + r")(?:ش|شون|ید|ی)?\b"


_VOL_N = r"(?:صدا|ولوم|ولیوم|volume|sound|audio)"
_VOL_V = _pv("ببر", "برسون", "برسان", "بذار", "بزار", "بگذار", "تنظیم", "ست", "بشه", "بشود", "باشه", "کن", "بکن", "بیار", "set", "put", "make", "turn", "raise",
             "lower", "increase", "decrease", "reduce", "adjust", "change", "up", "down", "louder", "quieter", "softer", "max", "half")
VOLUME_RX = re.compile(_VOL_N + r".*" + _VOL_V + "|" + _VOL_V + r".*" + _VOL_N, re.I | re.S)

_UNMUTE_WORDS = r"(?:آن\s*میوت|ان\s*میوت|\bun\s*-?\s*mute|بردار|در\s*بیار|دربیار|خارج|وصل|روشن)"
_MUTE_RX_S = (r"^(?!\s*(?:is|are|does|do|did|how|what|why|آیا)\b)(?!.*" + _UNMUTE_WORDS + r").*(?:\bmute\b|میوت|بی\s*صدا|سایلنت|\bsilence\b|"
              r"(?:صدا|ولوم|volume|sound|audio).*(?:قطع|خاموش)|(?:قطع|خاموش).*(?:صدا|ولوم|volume|sound|audio))")
_UNMUTE_RX_S = (r"\bun\s*-?\s*mute\b|آن\s*میوت|ان\s*میوت|(?:میوت|\bmute\b|بی\s*صدا|سایلنت)\w*\s*(?:رو|را|ش)?\s*(?:بردار|در\s*بیار|دربیار|خارج|بیرون|لغو|تموم|off)|"
                r"(?:صدا|ولوم|volume|sound|audio).*?(?:وصل|روشن)\s*(?:کن|بکن|کنید|بشه)|(?:از|out of)\s*(?:حالت\s*)?(?:میوت|mute)|\b(?:sound|audio|volume)\b.*?\b(?:back\s*)?on\b")
MUTE_RX = re.compile(_MUTE_RX_S, re.I | re.S)
UNMUTE_RX = re.compile(_UNMUTE_RX_S, re.I | re.S)
MUTE_ANY_RX = re.compile(_MUTE_RX_S + "|" + _UNMUTE_RX_S, re.I | re.S)

_DEV_N = (r"(?:خروجی|ورودی|هدفون|هدست|اسپیکر|بلندگو|میکروفون|میکروفن|\bmic\b|microphone|headphones?|headset|speakers?|output|input|دستگاه|device|ایرپاد|airpods|مانیتور|hdmi)")
_DEV_V = _pv("بذار", "بزار", "بگذار", "بزن", "عوض", "تغییر", "سوییچ", "سویچ", "switch", "set", "change", "use", "make", "select", "انتخاب", "بشه", "بشود", "باشه", "ببر",
             "وصل", "برگردون", "برگردان", "کن", "بکن") + r"|پیش\s*فرض|default"
DEFAULT_DEVICE_RX = re.compile(_DEV_N + r".*(?:" + _DEV_V + ")|(?:" + _DEV_V + r").*" + _DEV_N, re.I | re.S)


class AppsModule(WinModule):
    domain = "apps"

    def __init__(self, apps: AppTools):
        self.apps = apps

    def capabilities(self) -> list[Capability]:
        return [
            Capability("find_app", "apps", "check whether an app is installed (Start Menu, Steam, installed apps, Store), how it would be started, whether it is running, and list close matches",
                       self.apps.find_app, READ, (Param("name", "string", "app name", True),), ("apps",)),
            Capability("open_app", "apps", "open an installed app, Steam game or Windows tool by the exact name the user said, in Persian or English (for example Opera GX / «اپرا جی ایکس», Discord / «دیسکورد», Windscribe / «وینداسکرایب», Telegram / «تلگرام»); extract only the app name from the request; reuses a running instance",
                       self.apps.open_app, ACTION, (Param("name", "string", "only the app name, in the same language/pronunciation the user used; do not include «باز کن» or «برنامه»", True),), ("apps",),
                       intent_optout="باز کردن برنامه کم‌ریسک و برگشت‌پذیر است و دروازه‌ی نیت عمومی (protocol.GATES) قبلاً فقط برای درخواست‌های مربوط به برنامه‌ها ابزار را نشان می‌دهد؛ "
                                     "هیچ نمونه‌ی دومی هم ساخته نمی‌شود.",
                       memo=lambda a, t: f"open_app → {a.get('name')}", verifies_result=True, changes_system=True),
        ]


class BluetoothModule(WinModule):
    domain = "bluetooth"

    def __init__(self, bt: BluetoothTools):
        self.bt = bt

    def capabilities(self) -> list[Capability]:
        return [
            Capability("bluetooth_status", "bluetooth", "read the real Bluetooth state: on / off / adapter not found / access error / unknown (changes nothing)",
                       self.bt.status, READ, (), ("bluetooth", "system")),
            Capability("bluetooth_on", "bluetooth", "switch the Windows Bluetooth radio ON, then re-check and report the real state. ONLY when the user explicitly asks to turn Bluetooth on",
                       self.bt.turn_on, ACTION, (), ("bluetooth",), intent_rx=BT_ON_RX, memo=lambda a, t: "bluetooth_on → " + t[:80], verifies_result=True, changes_system=True),
            Capability("bluetooth_off", "bluetooth", "switch the Windows Bluetooth radio OFF, then re-check and report the real state. ONLY when the user explicitly asks to turn Bluetooth off",
                       self.bt.turn_off, ACTION, (), ("bluetooth",), intent_rx=BT_OFF_RX, memo=lambda a, t: "bluetooth_off → " + t[:80], verifies_result=True, changes_system=True),
        ]


class AudioModule(WinModule):
    """Windows Audio Manager (kira/tools/audio.py): reads are READ; every change is ACTION that needs an explicit request in the current message
    and is re-read from Windows afterwards. Nothing here knows about a Provider or model."""
    domain = "audio"

    def __init__(self, audio: AudioTools):
        self.audio = audio

    def capabilities(self) -> list[Capability]:
        a, cat = self.audio, ("audio",)
        direction = Param("direction", "string", "up = louder, down = quieter", True, None, ("up", "down"))
        amount = Param("amount", "integer", "percentage points, 1-100 (default 10)", False, 10)
        app = Param("app", "string", "application name or kind as the user said it (Discord, Chrome, browser, game ...)", True)
        return [
            Capability("audio_get_volume", "audio", "read the REAL Windows master volume (%), mute state, and the default output and input device (changes nothing)",
                       a.get_volume, READ, (), cat),
            Capability("audio_set_volume", "audio", "set the Windows master volume to an exact percent 0-100, then re-read and report it. Speakers/output only, not the microphone. ONLY when the user explicitly asks to set the volume",
                       a.set_volume, ACTION, (Param("percent", "integer", "target volume 0-100", True),), cat, intent_rx=VOLUME_RX,
                       memo=lambda x, t: "audio_set_volume → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_change_volume", "audio", "raise or lower the Windows master volume by N percentage points (default 10), then re-read and report it. Speakers/output only. ONLY when the user explicitly asks",
                       a.change_volume, ACTION, (direction, amount), cat, intent_rx=VOLUME_RX,
                       memo=lambda x, t: "audio_change_volume → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_mute", "audio", "mute the Windows speakers/output, then re-check the real mute state (not the microphone). ONLY when the user explicitly asks to mute",
                       a.mute, ACTION, (), cat, intent_rx=MUTE_RX, memo=lambda x, t: "audio_mute → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_unmute", "audio", "unmute the Windows speakers/output, then re-check the real mute state. ONLY when the user explicitly asks to unmute",
                       a.unmute, ACTION, (), cat, intent_rx=UNMUTE_RX, memo=lambda x, t: "audio_unmute → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_list_apps", "audio", "list apps that have an audio session (Volume Mixer) with their volume, mute and whether they are playing; marks likely games (changes nothing)",
                       a.list_apps, READ, (), cat),
            Capability("audio_set_app_volume", "audio", "set ONE application's volume (Volume Mixer) to an exact percent 0-100, then re-read it. app = name as the user said (a game: 'game' only if exactly one game plays). ONLY on explicit request",
                       a.set_app_volume, ACTION, (app, Param("percent", "integer", "target volume 0-100", True)), cat, intent_rx=VOLUME_RX,
                       memo=lambda x, t: "audio_set_app_volume → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_change_app_volume", "audio", "raise or lower ONE application's volume by N percentage points (default 10), then re-read it. ONLY on explicit request",
                       a.change_app_volume, ACTION, (app, direction, amount), cat, intent_rx=VOLUME_RX,
                       memo=lambda x, t: "audio_change_app_volume → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_set_app_mute", "audio", "mute (muted=true) or unmute (muted=false) ONE application, then re-check it. ONLY on explicit request",
                       a.set_app_mute, ACTION, (app, Param("muted", "boolean", "true = mute, false = unmute", True)), cat, intent_rx=MUTE_ANY_RX,
                       memo=lambda x, t: "audio_set_app_mute → " + t[:80], verifies_result=True, changes_system=True),
            Capability("audio_list_devices", "audio", "list audio output and/or input devices (active and disconnected) and show the current DEFAULT output and input device (changes nothing)",
                       a.list_devices, READ, (Param("kind", "string", "output | input | all (default all)", False, "all", ("output", "input", "all")),), cat),
            Capability("audio_set_default_device", "audio", "make a device the Windows DEFAULT output (speakers/headphones) or input (microphone), then re-read the defaults. device = name or type as the user said (headphones, speakers, a name). ONLY on explicit request",
                       a.set_default_device, ACTION, (Param("kind", "string", "output = speakers/headphones, input = microphone", True, None, ("output", "input")),
                                                      Param("device", "string", "device name or type as the user said it", True)),
                       cat, intent_rx=DEFAULT_DEVICE_RX, memo=lambda x, t: "audio_set_default_device → " + t[:80], verifies_result=True, changes_system=True),
        ]
