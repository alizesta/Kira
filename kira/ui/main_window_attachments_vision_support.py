"""Dependencies local to the attachments vision MainWindow feature adapter."""

import json
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QHBoxLayout, QFrame, QFileDialog, QSystemTrayIcon
from ..config import save_settings
from ..chat import attachments as att
from ..game_audio import GameAudioListener
from ..ui_widgets import AttachmentTile
from ..game_mode import CAPTURE_JPEG_QUALITY
from .workers import VisionAnalysisWorker
from .main_window_support import front_only
