"""Dependencies local to the lifecycle MainWindow feature adapter."""

import time
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu, QSystemTrayIcon
from ..config import save_settings, ROOT
from ..ollama_client import OllamaClient, model_installed, parse_keep_alive, clamp_num_ctx, clamp_num_predict
from ..hybrid_ai import HybridRouter
from .. import routes as route_model
from ..speech_fixes import SpeechFixes
from .. import evidence_memory
from .. import usage
from ..theme import build_style
from .. import winfx
from .workers import OllamaTaskWorker
from .main_window_support import SOUNDS_DIR
