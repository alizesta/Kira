"""Kira visual theme: neon glass surfaces for the desktop UI.

The layout and application behavior stay in main.py. This module only defines
Qt styles. On supported Windows 11 builds, Acrylic/Mica is supplied by DWM.
"""
STYLE = r"""
QMainWindow { background: #0A0A1C; }
QWidget { background: transparent; color: #EAF2FF; font-family: "Segoe UI", "Vazirmatn", Tahoma; font-size: 10pt; }
QLabel, QCheckBox, QRadioButton, QSlider, QToolButton { background: transparent; }

/* Neon Shooter-inspired navigation rail: compact, glassy and readable. */
QFrame#neonToolbar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(25,18,58,0.78), stop:0.52 rgba(10,27,48,0.76), stop:1 rgba(24,15,52,0.78));
    border: 1px solid rgba(111,91,210,0.62);
    border-bottom: 1px solid rgba(53,217,242,0.54);
    border-radius: 15px;
}
QToolButton#navTabBtn {
    background: rgba(12,17,39,0.52);
    border: 1px solid rgba(143,128,204,0.28);
    border-radius: 10px;
    padding: 5px;
}
QToolButton#navTabBtn:hover {
    background: rgba(72,54,132,0.42);
    border: 1px solid rgba(95,225,255,0.88);
}
QToolButton#navTabBtn:pressed {
    background: rgba(100,73,180,0.62);
    border: 1px solid #E5F9FF;
}
QToolButton#navTabBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(139,94,255,0.62), stop:1 rgba(42,190,224,0.34));
    border: 1px solid rgba(193,244,255,0.94);
}
QToolButton#navTabBtn:focus { border: 1px solid #FFFFFF; }
QLabel#characterPortrait {
    background: rgba(13,10,31,0.96);
    border: 1px solid rgba(90,224,255,0.72);
    border-radius: 12px;
    padding: 2px;
}
QGroupBox:hover { border: 1px solid rgba(111,226,255,0.76); }
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border: 1px solid rgba(87,219,255,0.68);
}
QComboBox:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #B9F5FF;
    background: rgba(75,64,130,0.20);
}
QCheckBox:hover, QRadioButton:hover { color: #FFFFFF; }
QSlider::handle:horizontal:hover {
    background: #FFFFFF;
    border: 2px solid #7CEBFF;
}
QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {
    background: rgba(75,205,238,0.16);
}
QLabel#title { font-size: 13pt; font-weight: 800; color: #A6F7FF; }
QLabel#hint { color: #A9B4D2; font-size: 9pt; }
QLabel#status { color: #8E9BC4; font-size: 8.5pt; }
QLabel#sectionTitle { color: #C8B8FF; font-size: 11pt; font-weight: 700; }
QToolTip { background: #120F26; color: #F0F6FF; border: 1px solid #8C63FF; border-radius: 7px; padding: 5px 8px; }

QFrame#avatarCard {
    background: rgba(140,99,255,0.07);
    border: 1px solid rgba(140,99,255,0.60); border-radius: 19px;
}
QFrame#chatCard {
    background: rgba(53,217,242,0.05); border: 1px solid rgba(53,217,242,0.42); border-radius: 19px;
}
QFrame#composer {
    background: rgba(140,99,255,0.08); border: 1px solid rgba(140,99,255,0.72); border-radius: 16px;
}
QTextEdit#chatView { background: transparent; border: none; padding: 3px; selection-background-color: rgba(140,99,255,0.45); }
QPlainTextEdit#chatInput { background: transparent; border: none; padding: 4px 6px; selection-background-color: rgba(140,99,255,0.45); }

QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: rgba(255,255,255,0.05); color: #EAF2FF; border: 1px solid rgba(255,255,255,0.24);
    border-radius: 10px; padding: 7px 10px; selection-background-color: rgba(140,99,255,0.45);
}
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #35D9F2;
}
QTextEdit#chatView:focus, QPlainTextEdit#chatInput:focus { border: none; }
QLineEdit:read-only { color: #AAB4D2; }

QPushButton {
    background: rgba(140,99,255,0.42); border: 1px solid #8C63FF; border-radius: 8px; padding: 3px 11px;
    color: #FFFFFF; font-weight: 600;
}
QPushButton:hover { background: rgba(140,99,255,0.66); border: 1px solid #DCCFFF; }
QPushButton:pressed { background: rgba(140,99,255,0.88); border: 1px solid #FFFFFF; }
QPushButton:disabled { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); color: #7C88A6; }
QPushButton:checked { background: rgba(53,217,242,0.42); border: 1px solid #35D9F2; }
QPushButton#save {
    background: rgba(53,217,242,0.38); border: 1px solid #35D9F2; padding: 3px 12px;
}
QPushButton#save:hover { background: rgba(53,217,242,0.62); border: 1px solid #B4F7FF; }

QToolButton { border: 1px solid transparent; border-radius: 9px; padding: 6px; color: #E2ECFF; }
QToolButton:hover { background: rgba(140,99,255,0.18); border: 1px solid rgba(140,99,255,0.60); }
QToolButton:pressed { background: rgba(140,99,255,0.38); border: 1px solid #C8B8FF; }
QToolButton:checked { background: rgba(53,217,242,0.22); border: 1px solid rgba(53,217,242,0.75); }
QToolButton:disabled { background: transparent; color: #66738F; }
QToolButton::menu-indicator { image: none; }
QToolButton#menuBtn { background: rgba(140,99,255,0.20); border: 1px solid rgba(140,99,255,0.70); border-radius: 11px; }
QToolButton#menuBtn:hover { background: rgba(140,99,255,0.42); border: 1px solid #DCCFFF; }
QToolButton#sendBtn {
    background: #8C63FF; border: 2px solid #E2DBFF; border-radius: 16px; padding: 0px;
}
QToolButton#sendBtn:hover { background: #A78BFF; border: 2px solid #FFFFFF; }
QToolButton#sendBtn:disabled { background: rgba(255,255,255,0.10); border: 2px solid rgba(255,255,255,0.18); }
QToolButton#routeChip {
    background: rgba(53,217,242,0.20); border: 2px solid rgba(53,217,242,0.80); border-radius: 12px;
    padding: 3px 11px; color: #DDFBFF; font-size: 8.5pt; font-weight: 800;
}
QToolButton#routeChip:hover { background: rgba(53,217,242,0.40); border: 2px solid #B4F7FF; }
QToolButton#genStop { background: #A83261; border: 1px solid #FF94C1; border-radius: 16px; padding: 0px; }
QToolButton#genStop:hover { background: #D3447C; border: 1px solid #FFD1E2; }

QComboBox {
    background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.26); border-radius: 9px;
    padding: 6px 9px; color: #EAF2FF; min-height: 18px;
}
QComboBox:hover { border: 1px solid rgba(140,99,255,0.80); }
QComboBox QAbstractItemView {
    background: #120F26; color: #EAF2FF; border: 1px solid #8C63FF;
    selection-background-color: rgba(140,99,255,0.45); selection-color: #FFFFFF; padding: 4px;
}
QMenu { background: #120F26; color: #EAF2FF; border: 1px solid #8C63FF; border-radius: 11px; padding: 6px; }
QMenu::item { padding: 8px 24px; border-radius: 7px; }
QMenu::item:selected { background: rgba(140,99,255,0.40); color: #FFFFFF; }
QMenu::item:disabled { color: #7786A1; }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.20); margin: 5px 9px; }

QGroupBox {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(140,99,255,0.38); border-radius: 14px;
    margin-top: 16px; padding: 16px 12px 10px 12px; font-weight: 650;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 7px; color: #C8B8FF; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; border: 1px solid rgba(255,255,255,0.20);
    padding: 8px 16px; margin: 2px; border-radius: 9px; color: #BCC8E4;
}
QTabBar::tab:selected { background: rgba(140,99,255,0.34); border: 2px solid #8C63FF; color: #FFFFFF; font-weight: 800; }
QTabBar::tab:hover:!selected { background: rgba(140,99,255,0.14); border: 1px solid rgba(140,99,255,0.60); }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: rgba(140,99,255,0.50); border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #8C63FF; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 3px; }
QScrollBar::handle:horizontal { background: rgba(140,99,255,0.50); border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 5px; background: rgba(255,255,255,0.16); border-radius: 2px; }
QSlider::handle:horizontal { background: #35D9F2; border: 1px solid #D2FAFF; width: 15px; margin: -6px 0; border-radius: 8px; }
QSlider::sub-page:horizontal { background: #8C63FF; border-radius: 2px; }
QCheckBox, QRadioButton { spacing: 8px; color: #E2EAFA; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.45); border-radius: 5px;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #8C63FF; border: 1px solid #E2DBFF; }
QListWidget, QTreeWidget, QTableWidget, QTableView {
    background: rgba(255,255,255,0.04); alternate-background-color: rgba(255,255,255,0.07); color: #EAF2FF;
    border: 1px solid rgba(255,255,255,0.24); border-radius: 10px; outline: 0;
}
QListWidget::item, QTreeWidget::item, QTableWidget::item { padding: 6px; border-radius: 5px; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
    background: rgba(140,99,255,0.42); color: #FFFFFF;
}
QHeaderView::section {
    background: rgba(140,99,255,0.14); color: #DDD5FF; border: none; border-bottom: 1px solid #8C63FF;
    padding: 7px 9px; font-weight: 700;
}
QProgressBar { background: rgba(255,255,255,0.06); border: 1px solid rgba(140,99,255,0.55); border-radius: 6px; text-align: center; color: #FFFFFF; }
QProgressBar::chunk { background: #8C63FF; border-radius: 5px; }

QFrame#attTile { background: rgba(255,255,255,0.05); border: 1px solid rgba(53,217,242,0.45); border-radius: 12px; }
QLabel#attThumb { background: rgba(255,255,255,0.05); border-radius: 8px; color: #A6F7FF; font-size: 12pt; font-weight: 800; }
QLabel#attOverlay { background: rgba(7,10,22,0.74); border-radius: 8px; color: #FFFFFF; font-size: 13pt; font-weight: 800; }
QToolButton#attClose { background: rgba(7,10,22,0.78); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.22); border-radius: 10px; padding: 0px; font-size: 8pt; }
QToolButton#attClose:hover { background: #A83261; border: 1px solid #FF94C1; }
QSplitter::handle { background: rgba(140,99,255,0.30); }
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


def build_style(effect="off", appearance=None):
    """Build the neon-glass stylesheet with user-controlled background, brightness and transparency."""
    appearance = appearance if isinstance(appearance, dict) else {}
    color = str(appearance.get("background_color") or "#0A0A1C").strip()
    if len(color) != 7 or not color.startswith("#"):
        color = "#0A0A1C"
    try:
        rgb = _hex_to_rgb(color)
    except (ValueError, TypeError):
        rgb = (10, 10, 28)
    brightness = max(40, min(150, int(appearance.get("brightness", 100)))) / 100.0
    transparency = max(0, min(100, int(appearance.get("transparency", 28))))
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
    for opaque, tint in GLASS_TINTS.items():
        css = css.replace(opaque, tint)
    glow = max(0, min(100, int(appearance.get("glow", 18))))
    cyan_alpha = min(0.98, 0.62 + glow * 0.0034)
    magenta_alpha = min(0.88, 0.34 + glow * 0.0048)
    override = f"""
QGroupBox {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(7,39,61,0.54), stop:0.48 rgba(20,24,65,0.48), stop:1 rgba(48,15,59,0.40));
    border: 1px solid rgba(53,217,242,{cyan_alpha:.2f});
    border-top: 2px solid rgba(104,245,255,{min(1.0, cyan_alpha + 0.02):.2f});
    border-bottom: 2px solid rgba(255,77,204,{magenta_alpha:.2f});
    border-radius: 14px;
}}
QGroupBox::title {{ color: #8AF5FF; font-weight: 800; }}
QGroupBox:hover {{
    border-color: rgba(255,77,204,{min(0.96, magenta_alpha + 0.12):.2f});
}}
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(25,198,226,0.66), stop:0.48 rgba(68,104,225,0.66), stop:1 rgba(147,73,206,0.68));
    border: 1px solid rgba(169,249,255,0.94);
    border-bottom: 2px solid rgba(255,102,220,0.92);
    border-radius: 10px;
    color: #FFFFFF;
    font-weight: 750;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(52,235,255,0.88), stop:0.48 rgba(92,133,255,0.86), stop:1 rgba(205,91,245,0.88));
    border-color: #FFFFFF;
}}
QPushButton:pressed {{
    background: rgba(37,198,226,0.86);
    border: 1px solid #FFFFFF;
}}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    border: 1px solid rgba(91,226,255,0.72);
    background: rgba(5,22,43,0.42);
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid #FF79DF;
    background: rgba(43,36,91,0.48);
}}
QTabBar::tab {{
    background: rgba(13,35,61,0.56);
    border: 1px solid rgba(76,211,245,0.60);
    color: #DDFBFF;
    border-radius: 9px;
    padding: 0.65em 1.1em;
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(30,210,237,0.70), stop:0.52 rgba(87,105,235,0.76), stop:1 rgba(177,68,203,0.72));
    border: 1px solid #B9FBFF;
    border-bottom: 2px solid #FF79DF;
    color: #FFFFFF;
    font-weight: 800;
}}
QTabBar::tab:hover:!selected {{
    background: rgba(53,217,242,0.22);
    border-color: rgba(255,113,220,0.90);
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: rgba(76,117,190,0.34);
    border: 1px solid rgba(53,217,242,0.36);
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22DDF2, stop:0.62 #438DFF, stop:1 #C65BFF);
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #7AF4FF;
    border: 2px solid #FFFFFF;
    width: 0.9em;
    margin: -0.45em 0;
    border-radius: 0.55em;
}}
QToolButton#menuBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(31,205,235,0.50), stop:1 rgba(139,79,220,0.54));
    border: 1px solid rgba(150,247,255,0.92);
    border-bottom: 2px solid rgba(255,91,216,0.90);
}}
QLabel#sectionTitle {{ color: #76F0FF; font-weight: 800; }}
QLabel#hint {{ color: #C4D8F5; }}
QToolButton:hover {{
    background: rgba(53,217,242,{0.14 + glow * 0.0032:.2f});
    border-color: rgba(255,112,220,{0.30 + glow * 0.0052:.2f});
}}
QProgressBar {{ border-color: rgba(53,217,242,0.78); }}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #24DDF2, stop:0.55 #6488FF, stop:1 #DA62EC);
}}
"""
    return css + "\n" + GLASS_OPAQUE + "\n" + override


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
    """Stylesheet for the active character; its tint follows the art and glow/transparency follow Appearance."""
    appearance = appearance if isinstance(appearance, dict) else {}
    r, g, b = appearance_tint(theme["deep"], appearance, cap=200)
    main, second = theme["main"], theme["second"]
    mr, mg, mb = _hex_to_rgb(main)
    sr, sg, sb = _hex_to_rgb(second)
    transparency = max(0, min(100, int(appearance.get("transparency", 28))))
    glow = max(0, min(100, int(appearance.get("glow", 58))))
    a_card = max(0.34, min(0.94, 0.86 - transparency * 0.0038))
    a_comp = max(0.38, min(0.98, 0.91 - transparency * 0.0028))
    if effect in ("mica", "acrylic"):
        a_card = min(a_card, 0.62 if effect == "mica" else 0.46)
        a_comp = min(a_comp, 0.70 if effect == "mica" else 0.56)
    border_alpha = 0.34 + glow * 0.0055
    return f"""
QFrame#avatarCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({r + 14},{g + 14},{b + 24},{a_card}), stop:1 rgba({r},{g},{b},{a_card}));
    border: 1px solid rgba({mr},{mg},{mb},{border_alpha:.2f}); border-radius: 19px;
}}
QFrame#chatCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({r + 10},{g + 10},{b + 20},{a_card}), stop:1 rgba({max(r - 6, 0)},{max(g - 6, 0)},{max(b - 4, 0)},{a_card}));
    border: 1px solid rgba({mr},{mg},{mb},{max(0.20, border_alpha - 0.05):.2f}); border-radius: 19px;
}}
QFrame#composer {{
    background: rgba({r + 22},{g + 22},{b + 34},{a_comp});
    border: 1px solid rgba({sr},{sg},{sb},{max(0.25, border_alpha):.2f}); border-radius: 16px;
}}
QLabel#title {{ color: {second}; }}
QTextEdit#chatView {{ selection-background-color: rgba({mr},{mg},{mb},0.55); }}
QToolButton#sendBtn {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {main}, stop:1 {second}); border: 1px solid rgba(255,255,255,0.55); }}
QToolButton#sendBtn:hover {{ border: 1px solid #FFFFFF; }}
QToolButton:checked {{ background: rgba({mr},{mg},{mb},0.30); border: 1px solid rgba({sr},{sg},{sb},0.75); }}
QToolButton:hover {{ background: rgba({sr},{sg},{sb},0.16); border: 1px solid rgba({sr},{sg},{sb},0.55); }}
QFrame#charTabs {{ background: transparent; border: none; }}
QPushButton#charTab {{
    background: rgba({r + 20},{g + 20},{b + 32},0.55); border: 1px solid rgba({mr},{mg},{mb},{0.12 + glow * 0.003:.2f});
    border-radius: 13px; padding: 7px 18px; color: #D8E2F6; font-weight: 700;
}}
QPushButton#charTab:hover {{ border: 1px solid rgba({sr},{sg},{sb},{0.25 + glow * 0.005:.2f}); color: #FFFFFF; }}
QPushButton#charTab:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({mr},{mg},{mb},0.62), stop:1 rgba({sr},{sg},{sb},0.40));
    border: 1px solid {main}; color: #FFFFFF;
}}
"""
