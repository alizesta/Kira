"""Dependencies local to the runtime MainWindow feature adapter."""

import random
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from ..config import save_settings, ROOT
from .. import storage
from ..core.exceptions import ChatHistoryError
from .. import routes as route_model
from ..leak_guard import scrub_lines
from ..chat_render import message_html
from ..listener import Listener
from .. import brain
from .. import mood
from .. import body as body_ctl
from ..chat.application_service import ChatApplicationService
from ..chat.commands import PermissionDecision
from .dialogs import MemoryDialog
from .main_window_support import SOUNDS_DIR
