"""Kira desktop visual theme.

Keeps Kira's established navy, violet and cyan palette while using restrained
surfaces, consistent control geometry and clear typographic hierarchy.
The module only defines Qt styles; application behavior remains elsewhere.
"""

STYLE = r"""
QMainWindow { background: #0A0A1C; }
QWidget {
    background: transparent;
    color: #EAF2FF;
    font-family: "Segoe UI", "Vazirmatn", Tahoma;
    font-size: 10pt;
}
QLabel, QCheckBox, QRadioButton, QSlider, QToolButton { background: transparent; }

/* Main navigation: one quiet surface, with colour reserved for selection. */
QFrame#neonToolbar {
    background: rgba(20, 18, 48, 0.88);
    border: 1px solid rgba(156, 123, 255, 0.18);
    border-radius: 14px;
}
QToolButton#navTabBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px;
}
QToolButton#navTabBtn:hover { background: rgba(140, 99, 255, 0.10); }
QToolButton#navTabBtn:pressed { background: rgba(140, 99, 255, 0.18); }
QToolButton#navTabBtn:checked {
    background: rgba(140, 99, 255, 0.20);
    border: 1px solid rgba(140, 99, 255, 0.30);
}
QToolButton#navTabBtn:focus { border: 1px solid rgba(53, 217, 242, 0.48); }

QLabel#characterPortrait {
    background: rgba(13, 10, 31, 0.96);
    border: 1px solid rgba(53, 217, 242, 0.24);
    border-radius: 10px;
    padding: 2px;
}
QLabel#title { font-size: 13pt; font-weight: 600; color: #A6F7FF; }
QLabel#sectionTitle { color: #C8B8FF; font-size: 11pt; font-weight: 600; }
QLabel#hint { color: #A9B4D2; font-size: 9pt; }
QLabel#status { color: #A9B4D2; font-size: 9pt; }
QToolTip {
    background: #120F26; color: #F0F6FF;
    border: 1px solid rgba(140, 99, 255, 0.28);
    border-radius: 6px; padding: 5px 8px;
}

/* Content panels use depth and spacing, not coloured outlines. */
QFrame#avatarCard, QFrame#chatCard, QFrame#composer {
    background: rgba(24, 21, 55, 0.72);
    border: 1px solid rgba(190, 190, 225, 0.10);
    border-radius: 14px;
}
QFrame#chatCard { background: rgba(16, 25, 48, 0.78); }
QFrame#composer { background: rgba(28, 23, 62, 0.86); }
QTextEdit#chatView {
    background: transparent; border: none; padding: 5px;
    selection-background-color: rgba(140, 99, 255, 0.38);
}
QPlainTextEdit#chatInput {
    background: transparent; border: none; padding: 6px 8px;
    selection-background-color: rgba(140, 99, 255, 0.38);
}

/* Inputs share one height, radius and focus treatment. */
QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: rgba(8, 12, 31, 0.62);
    color: #EAF2FF;
    border: 1px solid rgba(190, 200, 230, 0.16);
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: rgba(140, 99, 255, 0.38);
}
QTextEdit:hover, QPlainTextEdit:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: rgba(190, 200, 230, 0.28);
}
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid rgba(53, 217, 242, 0.58);
    background: rgba(18, 22, 48, 0.82);
}
QTextEdit#chatView:focus, QPlainTextEdit#chatInput:focus { border: none; }
QLineEdit:read-only { color: #AAB4D2; }

/* Buttons: clear primary/secondary hierarchy, no gradient fills. */
QPushButton {
    background: rgba(140, 99, 255, 0.18);
    border: 1px solid rgba(140, 99, 255, 0.30);
    border-radius: 8px;
    padding: 7px 13px;
    color: #F4F1FF;
    font-weight: 500;
    min-height: 18px;
}
QPushButton:hover {
    background: rgba(140, 99, 255, 0.26);
    border-color: rgba(140, 99, 255, 0.44);
}
QPushButton:pressed { background: rgba(140, 99, 255, 0.34); }
QPushButton:disabled {
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.08);
    color: #7C88A6;
}
QPushButton:checked {
    background: rgba(53, 217, 242, 0.14);
    border-color: rgba(53, 217, 242, 0.32);
}
QPushButton#save {
    background: rgba(53, 217, 242, 0.16);
    border-color: rgba(53, 217, 242, 0.34);
    color: #DDFBFF;
}
QPushButton#save:hover { background: rgba(53, 217, 242, 0.24); }

QToolButton {
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px;
    color: #E2ECFF;
}
QToolButton:hover {
    background: rgba(140, 99, 255, 0.12);
    border-color: rgba(140, 99, 255, 0.20);
}
QToolButton:pressed { background: rgba(140, 99, 255, 0.22); }
QToolButton:checked {
    background: rgba(53, 217, 242, 0.14);
    border-color: rgba(53, 217, 242, 0.26);
}
QToolButton:disabled { background: transparent; color: #66738F; }
QToolButton::menu-indicator { image: none; }
QToolButton#menuBtn {
    background: rgba(140, 99, 255, 0.12);
    border: 1px solid rgba(140, 99, 255, 0.22);
    border-radius: 9px;
}
QToolButton#sendBtn {
    background: #8C63FF;
    border: 1px solid rgba(226, 219, 255, 0.32);
    border-radius: 10px;
    padding: 0;
}
QToolButton#sendBtn:hover { background: #9A78FF; }
QToolButton#sendBtn:disabled {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.12);
}
QToolButton#routeChip {
    background: rgba(53, 217, 242, 0.10);
    border: 1px solid rgba(53, 217, 242, 0.22);
    border-radius: 8px;
    padding: 5px 10px;
    color: #DDFBFF;
    font-size: 9pt;
    font-weight: 500;
}
QToolButton#genStop {
    background: rgba(168, 50, 97, 0.48);
    border: 1px solid rgba(255, 148, 193, 0.22);
    border-radius: 10px;
    padding: 0;
}

QComboBox { min-height: 20px; }
QComboBox QAbstractItemView {
    background: #120F26; color: #EAF2FF;
    border: 1px solid rgba(153, 170, 210, 0.22);
    selection-background-color: rgba(140, 99, 255, 0.28);
    selection-color: #FFFFFF;
    padding: 4px;
}
QMenu {
    background: #120F26; color: #EAF2FF;
    border: 1px solid rgba(153, 170, 210, 0.20);
    border-radius: 8px; padding: 5px;
}
QMenu::item { padding: 7px 22px; border-radius: 5px; }
QMenu::item:selected { background: rgba(140, 99, 255, 0.22); color: #FFFFFF; }
QMenu::item:disabled { color: #7786A1; }
QMenu::separator { height: 1px; background: rgba(255, 255, 255, 0.10); margin: 5px 8px; }

QGroupBox {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(190, 200, 230, 0.12);
    border-radius: 12px;
    margin-top: 15px;
    padding: 15px 12px 10px;
    font-weight: 500;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #C8B8FF;
}
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    border: 1px solid transparent;
    padding: 8px 14px;
    margin: 1px;
    border-radius: 7px;
    color: #BCC8E4;
}
QTabBar::tab:selected {
    background: rgba(140, 99, 255, 0.18);
    border: 1px solid rgba(140, 99, 255, 0.28);
    color: #FFFFFF;
    font-weight: 600;
}
QTabBar::tab:hover:!selected { background: rgba(140, 99, 255, 0.08); }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical {
    background: rgba(140, 99, 255, 0.28);
    border-radius: 4px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: rgba(140, 99, 255, 0.44); }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 3px; }
QScrollBar::handle:horizontal {
    background: rgba(140, 99, 255, 0.28);
    border-radius: 4px; min-width: 32px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal {
    height: 5px; background: rgba(255, 255, 255, 0.14);
    border: none; border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #8C63FF; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #35D9F2; border: 1px solid rgba(210, 250, 255, 0.42);
    width: 14px; margin: -5px 0; border-radius: 7px;
}
QCheckBox, QRadioButton { spacing: 8px; color: #E2EAFA; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.30);
    border-radius: 4px;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: #8C63FF; border: 1px solid rgba(226, 219, 255, 0.54);
}
QListWidget, QTreeWidget, QTableWidget, QTableView {
    background: rgba(255, 255, 255, 0.025);
    alternate-background-color: rgba(255, 255, 255, 0.045);
    color: #EAF2FF;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px; outline: 0;
}
QListWidget::item, QTreeWidget::item, QTableWidget::item { padding: 6px; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
    background: rgba(140, 99, 255, 0.22); color: #FFFFFF;
}
QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {
    background: rgba(53, 217, 242, 0.08);
}
QHeaderView::section {
    background: rgba(140, 99, 255, 0.08);
    color: #DDD5FF; border: none;
    border-bottom: 1px solid rgba(140, 99, 255, 0.20);
    padding: 7px 9px; font-weight: 500;
}
QProgressBar {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(140, 99, 255, 0.18);
    border-radius: 5px; text-align: center; color: #FFFFFF;
}
QProgressBar::chunk { background: #8C63FF; border-radius: 4px; }

QFrame#attTile {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(53, 217, 242, 0.16);
    border-radius: 10px;
}
QLabel#attThumb {
    background: rgba(255, 255, 255, 0.04);
    border-radius: 7px; color: #A6F7FF;
    font-size: 12pt; font-weight: 600;
}
QLabel#attOverlay {
    background: rgba(7, 10, 22, 0.74);
    border-radius: 7px; color: #FFFFFF;
    font-size: 12pt; font-weight: 600;
}
QToolButton#attClose {
    background: rgba(7, 10, 22, 0.78); color: #FFFFFF;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 8px; padding: 0; font-size: 8pt;
}
QSplitter::handle { background: rgba(140, 99, 255, 0.16); }
"""

GLASS_OPAQUE = """
QDialog, QMessageBox, QFileDialog { background: #0F0C22; color: #EAF2FF; }
QMenu { background: #120F26; color: #EAF2FF; }
QToolTip { background: #120F26; color: #F0F6FF; }
QComboBox QAbstractItemView { background: #120F26; color: #EAF2FF; }
QDialog QListWidget { background: rgba(255,255,255,0.06); }
"""


def build_style(effect="off", appearance=None):
    """Build a restrained stylesheet while honoring the existing appearance controls."""
    appearance = appearance if isinstance(appearance, dict) else {}
    color = str(appearance.get("background_color") or "#0A0A1C").strip()
    try:
        rgb = _hex_to_rgb(color) if len(color) == 7 and color.startswith("#") else (10, 10, 28)
    except (ValueError, TypeError):
        rgb = (10, 10, 28)
    try:
        brightness = max(40, min(150, int(appearance.get("brightness", 100)))) / 100.0
        transparency = max(0, min(100, int(appearance.get("transparency", 28))))
        accent_strength = max(0, min(100, int(appearance.get("glow", 58))))
    except (ValueError, TypeError):
        brightness, transparency, accent_strength = 1.0, 28, 58
    alpha = max(0.10, min(0.96, 1.0 - transparency / 115.0))
    if effect == "acrylic":
        alpha = min(alpha, 0.42)
    elif effect == "mica":
        alpha = min(alpha, 0.68)
    adjusted = tuple(max(0, min(255, round(c * brightness))) for c in rgb)
    css = STYLE.replace(
        "QMainWindow { background: #0A0A1C; }",
        f"QMainWindow {{ background: rgba({adjusted[0]},{adjusted[1]},{adjusted[2]},{alpha:.2f}); }}",
        1,
    )
    # Keep the legacy Glow control functional as a restrained accent-opacity control.
    accent_alpha = 0.08 + accent_strength * 0.0012
    css += f"\nQFrame#neonToolbar {{ border-color: rgba(156,123,255,{accent_alpha:.2f}); }}\n"
    return css + "\n" + GLASS_OPAQUE


# ---------------- per-character chat themes (neon glass; colours taken from each character's art) ----------------
# main: neon edge/glow colour; deep: dark tint of the glass; soft: lighter tint; bubble/name: assistant bubble colours.
CHARACTER_THEMES = {
    "kira": {"main": "#9C7BFF", "second": "#35D9F2", "deep": (10, 10, 28), "bubble": "#252052", "name": "#D9D0FF"},
    "ren":  {"main": "#FF5964", "second": "#35D9F2", "deep": (30, 8, 18),  "bubble": "#351824", "name": "#FFB0B7"},
    "mika": {"main": "#FF4D91", "second": "#58D9FF", "deep": (36, 8, 30), "bubble": "#3C1730", "name": "#FFB3D0"},
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


def appearance_tint(base, appearance, cap=255):
    """Mix a base glass colour with the user's background colour (35 %) and scale it by the brightness slider (40-150 %).
    Without this the chat cards ignored the Appearance colour and brightness controls."""
    appearance = appearance if isinstance(appearance, dict) else {}
    color = str(appearance.get("background_color") or "#0A0A1C").strip()
    try:
        bg = _hex_to_rgb(color) if len(color) == 7 and color.startswith("#") else (10, 10, 28)
    except (ValueError, TypeError):
        bg = (10, 10, 28)
    try:
        brightness = max(40, min(150, int(appearance.get("brightness", 100)))) / 100.0
    except (ValueError, TypeError):
        brightness = 1.0
    default = (10, 10, 28)
    # only a colour the user actually chose pulls the tint; the default background leaves the character colours untouched
    weight = 0.0 if bg == default else 0.35
    return tuple(max(0, min(cap, round((b * (1 - weight) + c * weight) * brightness))) for b, c in zip(base, bg))


def character_style(theme, effect="off", appearance=None):
    """Build restrained character surfaces without changing character accent colours."""
    appearance = appearance if isinstance(appearance, dict) else {}
    r, g, b = appearance_tint(theme["deep"], appearance, cap=200)
    main, second = theme["main"], theme["second"]
    mr, mg, mb = _hex_to_rgb(main)
    sr, sg, sb = _hex_to_rgb(second)
    transparency = max(0, min(100, int(appearance.get("transparency", 28))))
    try:
        glow = max(0, min(100, int(appearance.get("glow", 58))))
    except (ValueError, TypeError):
        glow = 58
    a_card = max(0.34, min(0.94, 0.86 - transparency * 0.0038))
    a_comp = max(0.38, min(0.98, 0.91 - transparency * 0.0028))
    if effect in ("mica", "acrylic"):
        a_card = min(a_card, 0.62 if effect == "mica" else 0.46)
        a_comp = min(a_comp, 0.70 if effect == "mica" else 0.56)
    accent_alpha = 0.10 + glow * 0.001
    return f"""
QFrame#avatarCard {{
    background: rgba({r},{g},{b},{a_card:.2f});
    border: 1px solid rgba({mr},{mg},{mb},{accent_alpha:.2f});
    border-radius: 14px;
}}
QFrame#chatCard {{
    background: rgba({max(r - 3, 0)},{max(g - 3, 0)},{max(b - 3, 0)},{a_card:.2f});
    border: 1px solid rgba({mr},{mg},{mb},{max(0.08, accent_alpha - 0.04):.2f});
    border-radius: 14px;
}}
QFrame#composer {{
    background: rgba({min(r + 12, 255)},{min(g + 12, 255)},{min(b + 16, 255)},{a_comp:.2f});
    border: 1px solid rgba({sr},{sg},{sb},{max(0.08, accent_alpha - 0.02):.2f});
    border-radius: 12px;
}}
QLabel#title {{ color: {second}; }}
QTextEdit#chatView {{ selection-background-color: rgba({mr},{mg},{mb},0.38); }}
QToolButton#sendBtn {{
    background: {main};
    border: 1px solid rgba(225,239,255,0.24);
    border-radius: 10px;
}}
QToolButton#sendBtn:hover {{ background: {main}; border-color: rgba(235,247,255,0.42); }}
QToolButton:checked {{
    background: rgba({mr},{mg},{mb},0.20);
    border: 1px solid rgba({sr},{sg},{sb},0.26);
}}
QToolButton:hover {{
    background: rgba({sr},{sg},{sb},0.10);
    border: 1px solid rgba({sr},{sg},{sb},0.18);
}}
QFrame#charTabs {{ background: transparent; border: none; }}
QPushButton#charTab {{
    background: rgba({r},{g},{b},0.62);
    border: 1px solid rgba({mr},{mg},{mb},0.14);
    border-radius: 8px; padding: 7px 16px;
    color: #D8E2F6; font-weight: 500;
}}
QPushButton#charTab:hover {{
    border-color: rgba({sr},{sg},{sb},0.24); color: #FFFFFF;
}}
QPushButton#charTab:checked {{
    background: rgba({mr},{mg},{mb},0.24);
    border: 1px solid rgba({mr},{mg},{mb},0.34);
    color: #FFFFFF;
}}
"""
