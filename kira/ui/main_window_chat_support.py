"""Dependencies local to the chat MainWindow feature adapter."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from ..config import save_settings
from .. import about
from ..chat import attachments as att
from ..actions import match_safe_action, run_safe_action
from ..chat_render import sources_html, message_html
from .. import modes
from .. import evidence_memory
from .. import brain
from .. import usage
from .. import mood
from .. import body as body_ctl
from ..chat.application_service import ApplicationEventKind
from ..chat.command_adapters import create_default_command_registry
from ..tools.tasks import parse_control as parse_tool_task_control
from .workers import SearchWorker, TaskWorker
