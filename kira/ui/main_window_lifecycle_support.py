"""Dependencies local to the lifecycle MainWindow feature adapter."""

import time
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu, QSystemTrayIcon
from ..config import save_settings, ROOT, DEFAULTS
from ..ollama_client import model_installed, parse_keep_alive, clamp_num_ctx, clamp_num_predict
from ..speech_fixes import SpeechFixes
from ..theme import build_style
from .. import winfx
from .main_window_support import SOUNDS_DIR
