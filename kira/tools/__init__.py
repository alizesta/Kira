"""Kira tool system: Computer Awareness + a unified, Provider-independent tool registry.

  registry.py  tool definition, validation, access levels, execution + error handling
  access.py    allowed folders and secret protection for every file operation
  sysinfo.py   live Windows information (time, hardware, usage, windows, network)
  fileops.py   search / read files; delete / move (confirmed)
  apps.py      open an app / file / folder / link (launch + reuse of running instances)
  appcatalog.py app discovery: Start Menu, Steam, installed-apps registry, Store apps, running processes / windows
  sysaccess.py Unified System Access Manager: permission levels, confirmation grants, explicit-request gate, taint, backends, journal (every tool passes through it)
  wincontrol.py Windows Control Layer: how a Windows capability is declared (permission, gate, backend) and registered
  winmodules.py declares the apps + Bluetooth + audio capabilities (future: wallpaper, tray, system)
  winrunner.py  shared, controlled Windows PowerShell runner (FixedScript only; data via KIRA_* environment variables)
  bluetooth.py Windows Bluetooth radio: status / on / off (Windows Runtime Radio API, verified after every change)
  audio.py     Windows Audio Manager: volume / mute, per-app volume, devices, default devices (Core Audio API, verified after every change)
  builtin.py   registers all tools
  protocol.py  text protocol every Provider can speak, stream gate, intent gate
  agent.py     the turn loop that connects the tools to the Hybrid Brain (HybridRouter)
"""
from .agent import ToolAgent
from .builtin import build_registry
from .registry import ToolRegistry, Tool, ToolResult, READ, ACTION, SENSITIVE

__all__ = ["ToolAgent", "build_registry", "ToolRegistry", "Tool", "ToolResult", "READ", "ACTION", "SENSITIVE"]
