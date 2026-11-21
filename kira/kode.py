"""Unified Kode coding subsystem.

Kode exposes one user-facing workflow while selecting the safest internal strategy:
read-only investigation, reviewed single-file patches, or autonomous multi-file work.
Legacy class names remain aliases so existing saved integrations keep working.
"""
from .chat_code import KodeEngine
from .auto_agent import KodeAutonomousEngine
from .chat_code_ui import Kode
from .app.coding_agent_application import KodeApplicationService

__all__ = [
    "Kode",
    "KodeEngine",
    "KodeAutonomousEngine",
    "KodeApplicationService",
]
