"""Visual theme: one stylesheet, two looks.

``build_style("off")``      solid dark theme.
``build_style("acrylic")`` / ``build_style("mica")``  "glass" theme for Windows 11: the window itself is transparent
(the DWM paints the blurred backdrop, see winfx.py) and every card/field is a translucent tint on top of it.
"""
STYLE = """
QMainWindow, QWidget { background: #14151d; color: #e8e9f1; font-family: "Segoe UI", "Vazirmatn", Tahoma; font-size: 10pt; }
QLabel, QCheckBox, QSlider, QToolButton { background: transparent; }
QLabel#title { font-size: 12.5pt; font-weight: 700; color: #d8ceff; }
QLabel#hint { color: #8a8fa6; font-size: 9pt; }
QLabel#status { color: #9aa0b8; font-size: 8.5pt; }
QToolTip { background: #232639; color: #e8e9f1; border: 1px solid #3a3e58; padding: 4px 6px; }

QFrame#avatarCard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1e2033, stop:1 #171925); border: 1px solid #2a2d40; border-radius: 14px; }
QFrame#chatCard { background: #1a1c27; border: 1px solid #2a2d40; border-radius: 14px; }
QFrame#composer { background: #222536; border: 1px solid #2f3349; border-radius: 14px; }
QTextEdit#chatView { background: transparent; border: none; padding: 2px; selection-background-color: #5a4a99; }
QPlainTextEdit#chatInput { background: transparent; border: none; padding: 2px 4px; selection-background-color: #5a4a99; }

QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox { background: #1d1f2d; border: 1px solid #2f3349; border-radius: 8px; padding: 6px 8px; }
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #7c64cc; }
QTextEdit#chatView:focus, QPlainTextEdit#chatInput:focus { border: none; }
QPushButton { background: #5d4a9c; border: none; border-radius: 8px; padding: 7px 14px; color: white; font-weight: 600; }
QPushButton:hover { background: #7059b8; }
QPushButton:pressed { background: #4f3f87; }
QPushButton:disabled { background: #353849; color: #8d90a3; }
QPushButton:checked { background: #2fa98f; }
QPushButton#save { background: #2fa98f; padding: 5px 14px; }
QPushButton#save:hover { background: #3bbb9f; }

QToolButton { border: none; border-radius: 8px; padding: 6px; }
QToolButton:hover { background: #262a3d; }
QToolButton:pressed { background: #2f3350; }
QToolButton:checked { background: #2b2850; }
QToolButton:disabled { background: transparent; }
QToolButton::menu-indicator { image: none; }
QToolButton#sendBtn { background: #7c64cc; border-radius: 16px; padding: 0px; }
QToolButton#sendBtn:hover { background: #9078dd; }
QToolButton#sendBtn:disabled { background: #353849; }
QToolButton#routeChip { background: #1d1f2d; border: 1px solid #30344b; border-radius: 11px; padding: 3px 10px; color: #c9cde0; font-size: 8.5pt; }
QToolButton#routeChip:hover { background: #262a3d; border: 1px solid #4a4f72; }

QComboBox { background: #1d1f2d; border: 1px solid #2f3349; padding: 5px 8px; border-radius: 8px; }
QComboBox QAbstractItemView { background: #1d1f2d; border: 1px solid #2f3349; selection-background-color: #5d4a9c; }
QMenu { background: #1b1d29; border: 1px solid #30344b; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #2d2a52; }
QMenu::item:disabled { color: #6c7088; }
QMenu::separator { height: 1px; background: #2a2d40; margin: 4px 8px; }

QGroupBox { background: #1a1c27; border: 1px solid #2a2d40; border-radius: 12px; margin-top: 14px; padding: 14px 10px 8px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #b9a7ff; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #1d1f2d; padding: 8px 16px; margin: 2px; border-radius: 8px; color: #c9cbe0; }
QTabBar::tab:selected { background: #5d4a9c; color: white; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #34384e; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a4f6c; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: #34384e; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 5px; background: #2f3349; border-radius: 2px; }
QSlider::handle:horizontal { background: #b9a7ff; width: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #6c56a5; border-radius: 2px; }
QToolButton#genStop { background: #b5475a; border-radius: 16px; padding: 0px; }
QToolButton#genStop:hover { background: #cf5a6e; }

QFrame#attTile { background: #222536; border: 1px solid #2f3349; border-radius: 12px; }
QLabel#attThumb { background: #1d1f2d; border-radius: 8px; color: #b9a7ff; font-size: 12pt; font-weight: 700; }
QLabel#attOverlay { background: rgba(10,10,20,0.66); border-radius: 8px; color: #ffffff; font-size: 13pt; font-weight: 700; }
QToolButton#attClose { background: rgba(0,0,0,0.60); color: #ffffff; border-radius: 10px; padding: 0px; font-size: 8pt; }
QToolButton#attClose:hover { background: #b5475a; }
"""

# Opaque surface -> translucent tint used in glass mode.
GLASS_TINTS = {'#1a1c27': 'rgba(26,28,39,0.50)', '#222536': 'rgba(36,38,56,0.58)', '#1d1f2d': 'rgba(30,32,46,0.55)', '#1e2033': 'rgba(34,36,58,0.50)', '#171925': 'rgba(24,26,40,0.45)', '#262a3d': 'rgba(255,255,255,0.09)', '#2f3349': 'rgba(255,255,255,0.10)', '#2a2d40': 'rgba(255,255,255,0.08)', '#30344b': 'rgba(255,255,255,0.10)'}

# Windows that DWM does not blend must stay opaque even in glass mode (menus, dialogs, tooltips, combo popups).
GLASS_OPAQUE = """
QDialog, QMessageBox, QFileDialog { background: #181a26; }
QMenu { background: #1b1d29; }
QToolTip { background: #232639; }
QComboBox QAbstractItemView { background: #1d1f2d; }
QListWidget { background: rgba(20,22,32,0.45); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }
QDialog QListWidget { background: #14151d; }
"""


def build_style(effect="off"):
    """Stylesheet for the window effect: 'off' | 'mica' | 'acrylic'."""
    if effect not in ("mica", "acrylic"):
        return STYLE
    alpha = "0.30" if effect == "acrylic" else "0.55"            # Mica is nearly flat, so it needs a stronger tint than Acrylic
    css = STYLE.replace("QMainWindow, QWidget { background: #14151d;", "QMainWindow, QWidget { background: transparent;", 1)
    for opaque, tint in GLASS_TINTS.items():
        css = css.replace(opaque, tint)
    return css + f"\nQMainWindow {{ background: rgba(14,15,22,{alpha}); }}\n" + GLASS_OPAQUE
