"""Dependencies local to the character settings MainWindow feature adapter."""

import base64
import json
import time
import re
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QTabWidget, QToolButton, QInputDialog, QGraphicsDropShadowEffect, QColorDialog
from ..config import save_settings, ROOT, VERSION, DATA_DIR, APP_NAME, PROJECT_URL, RELEASES_URL
from .. import about
from .. import websearch
from .. import mood
from ..character.traits import BASE_TRAITS
from .. import avatar_art
from ..rig import MOODS
from ..ui_icons import make_icon, set_glow_intensity
from ..theme import build_style
from .. import winfx
from .components import McpRegistryPanel
from .pages import AppearancePage, CharactersPage, HelpPage, PreferencesPage
