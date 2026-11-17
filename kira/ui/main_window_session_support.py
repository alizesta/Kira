"""Dependencies local to the session MainWindow feature adapter."""

import contextlib
import base64
import time
from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QTextCursor, QColor, QImage, QTextDocument
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton, QComboBox, QFormLayout, QSpinBox, QGroupBox, QSlider, QScrollArea, QToolButton, QFrame, QDoubleSpinBox
from ..config import save_settings, VERSION
from ..hybrid_ai import HybridRouter
from ..chat import attachments as att
from ..chat_render import message_html, detect_direction, bubble_accent
from ..voice import Speaker
from ..strings import STR
from .. import mood
from ..characters.kira import PROFILE as KIRA_PROFILE
from ..ui_icons import make_icon
from .. import theme as theme_mod
from ..chat.session_manager import SessionManager
from .main_window_support import front_only, SessionRelay
