"""Dependencies local to the provider settings MainWindow feature adapter."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QComboBox, QFormLayout, QTabWidget, QCheckBox, QScrollArea, QToolButton, QListWidget, QListWidgetItem, QAbstractItemView, QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QProgressBar
from .components import ApiPanel, ModelsPanel, ModelCombo, OllamaProviderPanel, RouteEditor
from .workers import BenchWorker, TaskWorker
from .main_window_support import front_only
