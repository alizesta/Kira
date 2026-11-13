"""Kira visual theme: neon glass surfaces for the desktop UI.

The layout and application behavior stay in main.py. This module only defines
Qt styles. On supported Windows 11 builds, Acrylic/Mica is supplied by DWM.
"""
STYLE = r"""
QMainWindow { background: #0A0A1C; }
QWidget { background: transparent; color: #EAF2FF; font-family: "Segoe UI", "Vazirmatn", Tahoma; font-size: 10pt; }
QLabel, QCheckBox, QRadioButton, QSlider, QToolButton { background: transparent; }
QLabel#title { font-size: 13pt; font-weight: 800; color: #7EF0FF; }
QLabel#hint { color: #A9B4D2; font-size: 9pt; }
QLabel#status { color: #8E9BC4; font-size: 8.5pt; }
QLabel#sectionTitle { color: #FF9BE6; font-size: 11pt; font-weight: 700; }
QToolTip { background: #120F26; color: #F0F6FF; border: 1px solid #FF4FC8; border-radius: 7px; padding: 5px 8px; }

QFrame#avatarCard {
    background: rgba(255,79,200,0.07);
    border: 1px solid rgba(255,79,200,0.60); border-radius: 19px;
}
QFrame#chatCard {
    background: rgba(57,232,255,0.05); border: 1px solid rgba(57,232,255,0.42); border-radius: 19px;
}
QFrame#composer {
    background: rgba(255,79,200,0.08); border: 1px solid rgba(255,79,200,0.72); border-radius: 16px;
}
QTextEdit#chatView { background: transparent; border: none; padding: 3px; selection-background-color: rgba(255,79,200,0.45); }
QPlainTextEdit#chatInput { background: transparent; border: none; padding: 4px 6px; selection-background-color: rgba(255,79,200,0.45); }

QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: rgba(255,255,255,0.05); color: #EAF2FF; border: 1px solid rgba(255,255,255,0.24);
    border-radius: 10px; padding: 7px 10px; selection-background-color: rgba(255,79,200,0.45);
}
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #39E8FF;
}
QTextEdit#chatView:focus, QPlainTextEdit#chatInput:focus { border: none; }
QLineEdit:read-only { color: #AAB4D2; }

QPushButton {
    background: rgba(255,79,200,0.42); border: 2px solid #FF4FC8; border-radius: 11px; padding: 7px 15px;
    color: #FFFFFF; font-weight: 800;
}
QPushButton:hover { background: rgba(255,79,200,0.66); border: 2px solid #FFA6EA; }
QPushButton:pressed { background: rgba(255,79,200,0.88); border: 2px solid #FFFFFF; }
QPushButton:disabled { background: rgba(255,255,255,0.05); border: 2px solid rgba(255,255,255,0.14); color: #7C88A6; }
QPushButton:checked { background: rgba(57,232,255,0.42); border: 2px solid #39E8FF; }
QPushButton#save {
    background: rgba(57,232,255,0.38); border: 2px solid #39E8FF; padding: 5px 16px;
}
QPushButton#save:hover { background: rgba(57,232,255,0.62); border: 2px solid #B4F7FF; }

QToolButton { border: 1px solid transparent; border-radius: 9px; padding: 6px; color: #E2ECFF; }
QToolButton:hover { background: rgba(255,79,200,0.18); border: 1px solid rgba(255,79,200,0.60); }
QToolButton:pressed { background: rgba(255,79,200,0.38); border: 1px solid #FF9BE6; }
QToolButton:checked { background: rgba(57,232,255,0.22); border: 1px solid rgba(57,232,255,0.75); }
QToolButton:disabled { background: transparent; color: #66738F; }
QToolButton::menu-indicator { image: none; }
QToolButton#menuBtn { background: rgba(255,79,200,0.20); border: 1px solid rgba(255,79,200,0.70); border-radius: 11px; }
QToolButton#menuBtn:hover { background: rgba(255,79,200,0.42); border: 1px solid #FFA6EA; }
QToolButton#sendBtn {
    background: #FF4FC8; border: 2px solid #FFC2F0; border-radius: 16px; padding: 0px;
}
QToolButton#sendBtn:hover { background: #FF78D8; border: 2px solid #FFFFFF; }
QToolButton#sendBtn:disabled { background: rgba(255,255,255,0.10); border: 2px solid rgba(255,255,255,0.18); }
QToolButton#routeChip {
    background: rgba(57,232,255,0.20); border: 2px solid rgba(57,232,255,0.80); border-radius: 12px;
    padding: 3px 11px; color: #DDFBFF; font-size: 8.5pt; font-weight: 800;
}
QToolButton#routeChip:hover { background: rgba(57,232,255,0.40); border: 2px solid #B4F7FF; }
QToolButton#genStop { background: #A83261; border: 1px solid #FF94C1; border-radius: 16px; padding: 0px; }
QToolButton#genStop:hover { background: #D3447C; border: 1px solid #FFD1E2; }

QComboBox {
    background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.26); border-radius: 9px;
    padding: 6px 9px; color: #EAF2FF; min-height: 18px;
}
QComboBox:hover { border: 1px solid rgba(255,79,200,0.80); }
QComboBox QAbstractItemView {
    background: #120F26; color: #EAF2FF; border: 1px solid #FF4FC8;
    selection-background-color: rgba(255,79,200,0.45); selection-color: #FFFFFF; padding: 4px;
}
QMenu { background: #120F26; color: #EAF2FF; border: 1px solid #FF4FC8; border-radius: 11px; padding: 6px; }
QMenu::item { padding: 8px 24px; border-radius: 7px; }
QMenu::item:selected { background: rgba(255,79,200,0.40); color: #FFFFFF; }
QMenu::item:disabled { color: #7786A1; }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.20); margin: 5px 9px; }

QGroupBox {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,79,200,0.38); border-radius: 14px;
    margin-top: 16px; padding: 16px 12px 10px 12px; font-weight: 650;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 7px; color: #FF9BE6; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; border: 1px solid rgba(255,255,255,0.20);
    padding: 8px 16px; margin: 2px; border-radius: 9px; color: #BCC8E4;
}
QTabBar::tab:selected { background: rgba(255,79,200,0.34); border: 2px solid #FF4FC8; color: #FFFFFF; font-weight: 800; }
QTabBar::tab:hover:!selected { background: rgba(255,79,200,0.14); border: 1px solid rgba(255,79,200,0.60); }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: rgba(255,79,200,0.50); border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #FF4FC8; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 3px; }
QScrollBar::handle:horizontal { background: rgba(255,79,200,0.50); border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 5px; background: rgba(255,255,255,0.16); border-radius: 2px; }
QSlider::handle:horizontal { background: #39E8FF; border: 1px solid #D2FAFF; width: 15px; margin: -6px 0; border-radius: 8px; }
QSlider::sub-page:horizontal { background: #FF4FC8; border-radius: 2px; }
QCheckBox, QRadioButton { spacing: 8px; color: #E2EAFA; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.45); border-radius: 5px;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #FF4FC8; border: 1px solid #FFC2F0; }
QListWidget, QTreeWidget, QTableWidget, QTableView {
    background: rgba(255,255,255,0.04); alternate-background-color: rgba(255,255,255,0.07); color: #EAF2FF;
    border: 1px solid rgba(255,255,255,0.24); border-radius: 10px; outline: 0;
}
QListWidget::item, QTreeWidget::item, QTableWidget::item { padding: 6px; border-radius: 5px; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
    background: rgba(255,79,200,0.42); color: #FFFFFF;
}
QHeaderView::section {
    background: rgba(255,79,200,0.14); color: #FFD3F3; border: none; border-bottom: 1px solid #FF4FC8;
    padding: 7px 9px; font-weight: 700;
}
QProgressBar { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,79,200,0.55); border-radius: 6px; text-align: center; color: #FFFFFF; }
QProgressBar::chunk { background: #FF4FC8; border-radius: 5px; }

QFrame#attTile { background: rgba(255,255,255,0.05); border: 1px solid rgba(57,232,255,0.45); border-radius: 12px; }
QLabel#attThumb { background: rgba(255,255,255,0.05); border-radius: 8px; color: #7EF0FF; font-size: 12pt; font-weight: 800; }
QLabel#attOverlay { background: rgba(7,10,22,0.74); border-radius: 8px; color: #FFFFFF; font-size: 13pt; font-weight: 800; }
QToolButton#attClose { background: rgba(7,10,22,0.78); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.22); border-radius: 10px; padding: 0px; font-size: 8pt; }
QToolButton#attClose:hover { background: #A83261; border: 1px solid #FF94C1; }
QSplitter::handle { background: rgba(255,79,200,0.30); }
"""

# Surfaces in STYLE are already translucent, so no opaque-to-glass token swap is needed any more.
GLASS_TINTS = {}

# Popups are kept opaque for legibility; DWM backdrop effects apply to the main window.
GLASS_OPAQUE = """
QDialog, QMessageBox, QFileDialog { background: #0F0C22; color: #EAF2FF; }
QMenu { background: #120F26; color: #EAF2FF; }
QToolTip { background: #120F26; color: #F0F6FF; }
QComboBox QAbstractItemView { background: #120F26; color: #EAF2FF; }
QDialog QListWidget { background: rgba(255,255,255,0.06); }
"""


def build_style(effect="off"):
    """Return the neon stylesheet for 'off', 'mica', or 'acrylic'."""
    if effect not in ("mica", "acrylic"):
        return STYLE
    alpha = "0.34" if effect == "acrylic" else "0.62"
    css = STYLE.replace(
        "QMainWindow { background: #0A0A1C; }",
        f"QMainWindow {{ background: rgba(7,10,22,{alpha}); }}",
        1,
    )
    for opaque, tint in GLASS_TINTS.items():
        css = css.replace(opaque, tint)
    return css + "\n" + GLASS_OPAQUE


# ---------------- per-character chat themes (neon glass; colours taken from each character's art) ----------------
# main: neon edge/glow colour; deep: dark tint of the glass; soft: lighter tint; bubble/name: assistant bubble colours.
CHARACTER_THEMES = {
    "kira": {"main": "#8F6BFF", "second": "#4FD8FF", "deep": (22, 14, 52), "bubble": "#2A2358", "name": "#C9B8FF"},
    "ren":  {"main": "#FF4D5E", "second": "#2CE0A4", "deep": (40, 8, 16),  "bubble": "#3A1620", "name": "#FF9AA5"},
    "mika": {"main": "#FF6FC6", "second": "#58D9FF", "deep": (44, 12, 46), "bubble": "#40204A", "name": "#FFB3E4"},
}
_FALLBACK_THEME = CHARACTER_THEMES["kira"]


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def character_theme(character_id, profile=None):
    """Theme of a character. A custom character may bring its own colour (profile["theme_color"]); otherwise Kira's."""
    base = dict(CHARACTER_THEMES.get(str(character_id or "").lower(), _FALLBACK_THEME))
    color = str((profile or {}).get("theme_color") or "").strip()
    if len(color) == 7 and color.startswith("#"):
        try:
            r, g, b = _hex_to_rgb(color)
            base.update(main=color, deep=(r // 6, g // 6, b // 6), bubble="#%02X%02X%02X" % (r // 4 + 18, g // 4 + 18, b // 4 + 18), name=color)
        except ValueError:
            pass
    return base


def chat_accent(theme):
    return {"bubble": theme["bubble"], "name": theme["name"]}


def character_style(theme, effect="off"):
    """Stylesheet for the chat page of one character: glass cards whose tint, edge and tabs follow the character.
    Still glass (translucent, so Mica/Acrylic shows through) and still neon (bright gradient edge, glowing controls)."""
    r, g, b = theme["deep"]
    main, second = theme["main"], theme["second"]
    mr, mg, mb = _hex_to_rgb(main)
    sr, sg, sb = _hex_to_rgb(second)
    a_card = 0.50 if effect in ("mica", "acrylic") else 0.78
    a_comp = 0.58 if effect in ("mica", "acrylic") else 0.86
    return f"""
QFrame#avatarCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({r + 14},{g + 14},{b + 24},{a_card}), stop:1 rgba({r},{g},{b},{a_card}));
    border: 1px solid rgba({mr},{mg},{mb},0.85); border-radius: 19px;
}}
QFrame#chatCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({r + 10},{g + 10},{b + 20},{a_card}), stop:1 rgba({max(r - 6, 0)},{max(g - 6, 0)},{max(b - 4, 0)},{a_card}));
    border: 1px solid rgba({mr},{mg},{mb},0.80); border-radius: 19px;
}}
QFrame#composer {{
    background: rgba({r + 22},{g + 22},{b + 34},{a_comp});
    border: 1px solid rgba({sr},{sg},{sb},0.80); border-radius: 16px;
}}
QLabel#title {{ color: {second}; }}
QTextEdit#chatView {{ selection-background-color: rgba({mr},{mg},{mb},0.55); }}
QToolButton#sendBtn {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {main}, stop:1 {second}); border: 1px solid rgba(255,255,255,0.55); }}
QToolButton#sendBtn:hover {{ border: 1px solid #FFFFFF; }}
QToolButton:checked {{ background: rgba({mr},{mg},{mb},0.30); border: 1px solid rgba({sr},{sg},{sb},0.75); }}
QToolButton:hover {{ background: rgba({sr},{sg},{sb},0.16); border: 1px solid rgba({sr},{sg},{sb},0.55); }}
QFrame#charTabs {{ background: transparent; border: none; }}
QPushButton#charTab {{
    background: rgba({r + 20},{g + 20},{b + 32},0.55); border: 1px solid rgba({mr},{mg},{mb},0.35);
    border-radius: 13px; padding: 7px 18px; color: #D8E2F6; font-weight: 700;
}}
QPushButton#charTab:hover {{ border: 1px solid rgba({sr},{sg},{sb},0.85); color: #FFFFFF; }}
QPushButton#charTab:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({mr},{mg},{mb},0.62), stop:1 rgba({sr},{sg},{sb},0.40));
    border: 1px solid {main}; color: #FFFFFF;
}}
"""
