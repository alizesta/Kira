"""Dependencies local to the voice settings MainWindow feature adapter."""

import json
import time
import shutil
import subprocess
from pathlib import Path
import re
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QFrame, QFileDialog, QSizePolicy, QInputDialog, QStackedWidget, QButtonGroup, QGraphicsDropShadowEffect
from ..config import DATA_DIR
from ..ollama_client import clamp_num_ctx, clamp_num_predict, DEFAULT_NUM_PREDICT, DEFAULT_NUM_CTX, DEFAULT_KEEP_ALIVE
from ..vrm_avatar import KiraAvatar
from ..listener import Listener
from ..ui_icons import make_icon
from ..ui_widgets import ChatInput, RouteChip
from ..chat_code_ui import CodeChat
from .components import ChatHeader, ModelCombo, ChatComposer
from .pages import AssistantPage, VoicePage
from .workers import TaskWorker
