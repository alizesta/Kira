"""Dependencies local to the root MainWindow feature adapter."""

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget, QToolButton, QMenu, QFrame, QGridLayout
from ..config import load_settings, ROOT, LOAD_WARNINGS, DATA_DIR
from ..chat import attachments as att
from ..companion import CompanionWindow, CompanionBubble
from ..emotion.backend_png import EmotionFaceAnimator
from ..emotion.director import EmotionDirector
from ..ui_icons import make_icon
from ..ui_widgets import AttachmentTile
from ..chat_sessions import ChatSession, session_property, front_only_property
from ..chat.session_manager import SessionManager
from .. import winfx
from .controllers import ChatAttachmentController
from .main_window_support import load_reactions
