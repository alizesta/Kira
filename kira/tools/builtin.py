"""All built-in tools in one place. To add a tool: write a handler and register it here (nothing else needs to change)."""
from __future__ import annotations

from . import sysinfo
from .access import PathPolicy
from .apps import AppTools
from .bluetooth import BluetoothTools
from .fileops import FileTools
import re

from .registry import ToolRegistry, Tool, Param, READ, ACTION, SENSITIVE

_BT_WORD = r"(?:بلو\s*توث|بلو\s*توس|bluetooth)"
_BT_ON_RX = re.compile(_BT_WORD + r".*(?:روشن|فعال|وصل|بزن|\bon\b|enable|turn\s*on|switch\s*on|start)|(?:روشن|فعال|turn\s*on|switch\s*on|enable)\s*.*" + _BT_WORD, re.I)
_BT_OFF_RX = re.compile(_BT_WORD + r".*(?:خاموش|غیر\s*فعال|قطع|\boff\b|disable|turn\s*off|switch\s*off|stop)|(?:خاموش|غیر\s*فعال|قطع|turn\s*off|switch\s*off|disable)\s*.*" + _BT_WORD, re.I)


def _paths_memo(args, text):
    lines = [ln for ln in text.splitlines() if ln[:2].rstrip(". ").isdigit() and ":\\" in ln]
    if not lines:
        return None
    return "search_files → " + " | ".join(ln.split(" — ")[0] for ln in lines[:5])


def build_registry(policy: PathPolicy) -> ToolRegistry:
    reg = ToolRegistry()
    files, apps = FileTools(policy), AppTools(policy)

    # ---------------- level 1: read only ----------------
    reg.register(Tool("get_datetime", "exact date, time (Gregorian + Persian calendar), weekday and time zone from the PC clock",
                      lambda a: sysinfo.datetime_text(), (), READ, ("time",)))
    reg.register(Tool("get_system_info", "Windows version, PC name, system language, CPU model, total RAM, GPU model",
                      lambda a: sysinfo.system_info_text(), (), READ, ("system",)))
    reg.register(Tool("get_resource_usage", "live CPU %, RAM used/free, GPU use (NVIDIA) and battery",
                      lambda a: sysinfo.usage_text(a.get("part", "all")),
                      (Param("part", "string", "which part", False, "all", ("all", "cpu", "ram", "gpu", "battery")),), READ, ("system",)))
    reg.register(Tool("get_disks", "total and free space of every drive", lambda a: sysinfo.disks_text(), (), READ, ("system", "files")))
    reg.register(Tool("get_network_info", "internet connectivity check, PC name and local IP addresses",
                      lambda a: sysinfo.network_text(), (), READ, ("system",)))
    reg.register(Tool("list_running_apps", "apps that have an open window now (include_background=true also lists top processes by RAM)",
                      lambda a: sysinfo.running_apps_text(bool(a.get("include_background", False))),
                      (Param("include_background", "boolean", "also list background processes", False, False),), READ, ("apps", "system")))
    reg.register(Tool("get_active_window", "the window / app the user is currently using",
                      lambda a: sysinfo.active_window_text(), (), READ, ("apps",)))
    reg.register(Tool("find_app", "check whether an app is installed (Start Menu, Steam, installed apps, Store), how it would be started, whether it is running, and list close matches",
                      apps.find_app, (Param("name", "string", "app name", True),), READ, ("apps",)))
    reg.register(Tool("list_allowed_folders", "the folders Kira is allowed to search / read / open",
                      lambda a: "پوشه‌های مجاز:\n" + "\n".join("- " + p for p in policy.root_labels()), (), READ, ("files",)))
    reg.register(Tool("search_files", "find files by name words, extension and/or date (date: today | yesterday | YYYY-MM-DD; within_days: N)",
                      files.search_files,
                      (Param("query", "string", "words in the file name"), Param("extension", "string", "e.g. pdf, docx, txt"),
                       Param("date", "string", "today | yesterday | YYYY-MM-DD (modified or created that day)"),
                       Param("within_days", "integer", "modified/created within the last N days"),
                       Param("folder", "string", "optional full path of an allowed folder to search in"),
                       Param("max_results", "integer", "default 15, max 40", False, 15)),
                      READ, ("files",), memo=_paths_memo))
    reg.register(Tool("list_folder", "list files and sub-folders of an allowed folder", files.list_folder,
                      (Param("path", "string", "full folder path", True), Param("max_items", "integer", "default 40", False, 40)), READ, ("files",)))
    reg.register(Tool("file_info", "size, dates and type of a file or folder", files.file_info,
                      (Param("path", "string", "full path", True),), READ, ("files",)))
    reg.register(Tool("read_file", "read the text of a text/code/CSV/JSON, DOCX or PDF file (long files: use start to continue)", files.read_file,
                      (Param("path", "string", "full file path", True), Param("max_chars", "integer", "default 6000, max 12000", False, 6000),
                       Param("start", "integer", "character offset to continue from", False, 0)),
                      READ, ("files",), memo=lambda a, t: f"read_file → {a.get('path')}", max_chars=13000))

    # ---------------- level 2: ordinary actions ----------------
    reg.register(Tool("open_app", "open an installed app, Steam game or Windows tool by name (Discord, Notepad, Chrome, Wallpaper Engine ...); reuses a running instance", apps.open_app,
                      (Param("name", "string", "app name as the user said it", True),), ACTION, ("apps",),
                      memo=lambda a, t: f"open_app → {a.get('name')}"))
    reg.register(Tool("open_path", "open a file (default program) or a folder (File Explorer) inside the allowed folders", apps.open_path,
                      (Param("path", "string", "full path", True),), ACTION, ("files",), memo=lambda a, t: f"open_path → {a.get('path')}"))
    reg.register(Tool("open_url", "open an http/https link in the default browser", apps.open_url,
                      (Param("url", "string", "full http(s) link", True),), ACTION, ("apps",)))

    bt = BluetoothTools()
    reg.register(Tool("bluetooth_status", "read the real Bluetooth state: on / off / adapter not found / access error / unknown (changes nothing)", bt.status, (), READ, ("bluetooth", "system")))
    reg.register(Tool("bluetooth_on", "switch the Windows Bluetooth radio ON, then re-check and report the real state. ONLY when the user explicitly asks to turn Bluetooth on", bt.turn_on,
                      (), ACTION, ("bluetooth",), intent_rx=_BT_ON_RX, memo=lambda a, t: "bluetooth_on → " + t[:80]))
    reg.register(Tool("bluetooth_off", "switch the Windows Bluetooth radio OFF, then re-check and report the real state. ONLY when the user explicitly asks to turn Bluetooth off", bt.turn_off,
                      (), ACTION, ("bluetooth",), intent_rx=_BT_OFF_RX, memo=lambda a, t: "bluetooth_off → " + t[:80]))

    # ---------------- level 3: sensitive (always confirmed by the user first) ----------------
    reg.register(Tool("delete_file", "move ONE file to the Windows Recycle Bin (recoverable)", files.delete_file,
                      (Param("path", "string", "full file path", True),), SENSITIVE, ("files",),
                      confirm_summary=files.confirm_delete, precheck=files.precheck_delete))
    reg.register(Tool("move_file", "move ONE file into another allowed folder (never overwrites)", files.move_file,
                      (Param("source", "string", "full file path", True), Param("destination_folder", "string", "full destination folder path", True)),
                      SENSITIVE, ("files",), confirm_summary=files.confirm_move, precheck=files.precheck_move))
    return reg
