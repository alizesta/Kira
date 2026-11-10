"""Kira visual theme: neon glass surfaces for the desktop UI.

The layout and application behavior stay in main.py. This module only defines
Qt styles. On supported Windows 11 builds, Acrylic/Mica is supplied by DWM.
"""
STYLE = r"""
QMainWindow { background: #0A0F20; }
QWidget { background: transparent; color: #EAF2FF; font-family: "Segoe UI", "Vazirmatn", Tahoma; font-size: 10pt; }
QLabel, QCheckBox, QRadioButton, QSlider, QToolButton { background: transparent; }
QLabel#title { font-size: 13pt; font-weight: 800; color: #93E8FF; }
QLabel#hint { color: #A4B4D2; font-size: 9pt; }
QLabel#status { color: #8EA4C9; font-size: 8.5pt; }
QLabel#sectionTitle { color: #BDAEFF; font-size: 11pt; font-weight: 700; }
QToolTip { background: #111A31; color: #F0F6FF; border: 1px solid #4D8BB7; border-radius: 7px; padding: 5px 8px; }

QFrame#avatarCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #172744, stop:1 #121B32);
    border: 1px solid rgba(99,220,255,0.52); border-radius: 19px;
}
QFrame#chatCard {
    background: #111A31; border: 1px solid rgba(113,153,255,0.34); border-radius: 19px;
}
QFrame#composer {
    background: #202448; border: 1px solid rgba(151,133,255,0.62); border-radius: 16px;
}
QTextEdit#chatView { background: transparent; border: none; padding: 3px; selection-background-color: #5145A8; }
QPlainTextEdit#chatInput { background: transparent; border: none; padding: 4px 6px; selection-background-color: #5145A8; }

QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #121C32; color: #EAF2FF; border: 1px solid rgba(132,164,220,0.32);
    border-radius: 10px; padding: 7px 10px; selection-background-color: #5145A8;
}
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #68DFFF;
}
QTextEdit#chatView:focus, QPlainTextEdit#chatInput:focus { border: none; }
QLineEdit:read-only { color: #AAB8D2; }

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6653E8, stop:1 #493EAA);
    border: 1px solid rgba(181,164,255,0.54); border-radius: 10px; padding: 6px 11px;
    color: #FFFFFF; font-weight: 700;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #806CFF, stop:1 #5A55CF);
    border: 1px solid #9BEBFF;
}
QPushButton:pressed { background: #40368E; border: 1px solid #68DFFF; }
QPushButton:disabled { background: #303951; border: 1px solid #3B4963; color: #8290A9; }
QPushButton:checked { background: #147F91; border: 1px solid #6AEAFF; }
QPushButton#save {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #159A9A, stop:1 #287AAB);
    border: 1px solid rgba(105,239,238,0.75); padding: 6px 16px;
}
QPushButton#save:hover { background: #20B8B0; border: 1px solid #A0FFFF; }

QToolButton { border: 1px solid transparent; border-radius: 9px; padding: 4px; color: #DCEBFF; }
QToolButton:hover { background: rgba(99,220,255,0.13); border: 1px solid rgba(99,220,255,0.40); }
QToolButton:pressed { background: rgba(125,104,255,0.26); border: 1px solid rgba(157,141,255,0.72); }
QToolButton:checked { background: rgba(84,75,177,0.40); border: 1px solid rgba(118,222,255,0.66); }
QToolButton:disabled { background: transparent; color: #64738E; }
QToolButton::menu-indicator { image: none; }
QToolButton#menuBtn { background: rgba(29,43,73,0.76); border: 1px solid rgba(109,205,255,0.32); border-radius: 11px; }
QToolButton#menuBtn:hover { background: rgba(56,75,124,0.86); border: 1px solid #68DFFF; }
QToolButton#sendBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #24B8D9, stop:1 #6759F3);
    border: 1px solid rgba(166,247,255,0.92); border-radius: 16px; padding: 0px;
}
QToolButton#sendBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #53DFFF, stop:1 #8A79FF);
    border: 1px solid #FFFFFF;
}
QToolButton#sendBtn:disabled { background: #35415B; border: 1px solid #52617B; }
QToolButton#routeChip {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #173C58, stop:1 #302B62);
    border: 1px solid rgba(105,224,255,0.64); border-radius: 12px;
    padding: 3px 8px; color: #D9F8FF; font-size: 8.5pt; font-weight: 700;
}
QToolButton#routeChip:hover { background: #284A75; border: 1px solid #A1F0FF; }
QToolButton#genStop { background: #A83261; border: 1px solid #FF94C1; border-radius: 16px; padding: 0px; }
QToolButton#genStop:hover { background: #D3447C; border: 1px solid #FFD1E2; }

QComboBox {
    background: #121C32; border: 1px solid rgba(132,164,220,0.34); border-radius: 9px;
    padding: 6px 9px; color: #EAF2FF; min-height: 18px;
}
QComboBox:hover { border: 1px solid rgba(104,223,255,0.72); }
QComboBox QAbstractItemView {
    background: #111A31; color: #EAF2FF; border: 1px solid #527DAA;
    selection-background-color: #403B82; selection-color: #FFFFFF; padding: 4px;
}
QMenu { background: #111A31; color: #EAF2FF; border: 1px solid #527DAA; border-radius: 11px; padding: 6px; }
QMenu::item { padding: 8px 24px; border-radius: 7px; }
QMenu::item:selected { background: rgba(93,106,202,0.48); color: #FFFFFF; }
QMenu::item:disabled { color: #7786A1; }
QMenu::separator { height: 1px; background: rgba(123,164,218,0.28); margin: 5px 9px; }

QGroupBox {
    background: #111A31; border: 1px solid rgba(109,157,220,0.38); border-radius: 14px;
    margin-top: 16px; padding: 16px 12px 10px 12px; font-weight: 650;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 7px; color: #BDAEFF; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #17233D; border: 1px solid rgba(116,154,218,0.25);
    padding: 8px 16px; margin: 2px; border-radius: 9px; color: #B7C7E3;
}
QTabBar::tab:selected { background: #473F99; border: 1px solid #8CDEFF; color: #FFFFFF; }
QTabBar::tab:hover:!selected { background: #26365A; border: 1px solid rgba(104,223,255,0.48); }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: rgba(112,160,222,0.52); border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #68DFFF; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 3px; }
QScrollBar::handle:horizontal { background: rgba(112,160,222,0.52); border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 5px; background: #293754; border-radius: 2px; }
QSlider::handle:horizontal { background: #78E8FF; border: 1px solid #D2FAFF; width: 15px; margin: -6px 0; border-radius: 8px; }
QSlider::sub-page:horizontal { background: #7869F5; border-radius: 2px; }
QCheckBox, QRadioButton { spacing: 8px; color: #DCE8FA; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; background: #121C32; border: 1px solid #637FA9; border-radius: 5px;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #6559D9; border: 1px solid #83E9FF; }
QListWidget, QTreeWidget, QTableWidget, QTableView {
    background: #121C32; alternate-background-color: #17233D; color: #EAF2FF;
    border: 1px solid rgba(124,162,220,0.34); border-radius: 10px; outline: 0;
}
QListWidget::item, QTreeWidget::item, QTableWidget::item { padding: 6px; border-radius: 5px; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
    background: rgba(87,84,184,0.62); color: #FFFFFF;
}
QHeaderView::section {
    background: #1B2A49; color: #BFEFFF; border: none; border-bottom: 1px solid #527DAA;
    padding: 7px 9px; font-weight: 700;
}
QProgressBar { background: #17233D; border: 1px solid #49668C; border-radius: 6px; text-align: center; color: #FFFFFF; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #20B8D8, stop:1 #7666F2); border-radius: 5px; }

QFrame#attTile { background: #192747; border: 1px solid rgba(106,203,255,0.42); border-radius: 12px; }
QLabel#attThumb { background: #121C32; border-radius: 8px; color: #91E9FF; font-size: 12pt; font-weight: 800; }
QLabel#attOverlay { background: rgba(7,10,22,0.74); border-radius: 8px; color: #FFFFFF; font-size: 13pt; font-weight: 800; }
QToolButton#attClose { background: rgba(7,10,22,0.78); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.22); border-radius: 10px; padding: 0px; font-size: 8pt; }
QToolButton#attClose:hover { background: #A83261; border: 1px solid #FF94C1; }
QSplitter::handle { background: rgba(105,193,235,0.28); }

/* Neon Glow pass: stronger luminous edges and brighter active states */
QFrame#chatCard {
    background: rgba(10, 17, 37, 0.90);
    border: 1px solid #42DFFF;
    border-radius: 20px;
}
QFrame#composer {
    background: rgba(25, 20, 58, 0.94);
    border: 1px solid #A77BFF;
    border-radius: 17px;
}
QFrame#avatarCard {
    background: rgba(14, 27, 52, 0.90);
    border: 1px solid #45DFFF;
    border-radius: 20px;
}
QToolButton#routeChip {
    background: #102F4A;
    border: 1px solid #42E6FF;
    color: #D9FBFF;
}
QToolButton#routeChip:hover {
    background: #174A70;
    border: 1px solid #B5F8FF;
}
QToolButton#sendBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00D9FF, stop:0.48 #397BFF, stop:1 #A64DFF);
    border: 1px solid #D8FCFF;
    border-radius: 16px;
}
QToolButton#sendBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #63F0FF, stop:0.48 #689DFF, stop:1 #C78AFF);
    border: 1px solid #FFFFFF;
}
QToolButton#menuBtn, QToolButton {
    border-color: rgba(90, 220, 255, 0.20);
}
QToolButton:hover {
    background: rgba(52, 187, 255, 0.20);
    border: 1px solid #55E7FF;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #704BFF, stop:0.55 #4B5BDF, stop:1 #168FCA);
    border: 1px solid #9DDBFF;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #9679FF, stop:0.55 #6887FF, stop:1 #30C8EF);
    border: 1px solid #D9FBFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #55E7FF;
}
QTabBar::tab:selected {
    background: #44308E;
    border: 1px solid #65E8FF;
    color: #FFFFFF;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #5CEAFF;
}

/* Neon finish: luminous surfaces, brighter controls and clear colour identity per action. */
QFrame#chatCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(12,29,54,0.62), stop:0.52 rgba(17,22,48,0.66), stop:1 rgba(31,20,60,0.62));
    border: 1px solid #48E7FF;
    border-radius: 21px;
}
QFrame#avatarCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(13,39,66,0.62), stop:0.60 rgba(20,25,55,0.66), stop:1 rgba(39,21,67,0.62));
    border: 1px solid #5DEBFF;
    border-radius: 21px;
}
QFrame#composer {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(18,35,72,0.58), stop:0.55 rgba(35,27,78,0.62), stop:1 rgba(49,23,72,0.58));
    border: 1px solid #B58CFF;
    border-radius: 18px;
}
QLabel#title { color: #B7F7FF; }
QLabel#moodIndicator {
    background: rgba(25,22,68,0.98);
    border: 1px solid #A98AFF;
    border-radius: 11px;
    color: #F5ECFF;
    padding: 4px 9px;
}
QToolButton {
    border: 1px solid rgba(90,220,255,0.34);
    border-radius: 11px;
    padding: 7px;
    background: rgba(14,35,61,0.88);
}
QToolButton:hover {
    background: rgba(40,117,157,0.60);
    border: 1px solid #A4F6FF;
}
QToolButton:checked {
    background: rgba(75,53,139,0.78);
    border: 1px solid #D2B7FF;
}
/* Voice controls have distinct neon identities instead of the same flat grey icon. */
QToolButton#icon_mic {
    background: rgba(62,24,61,0.88);
    border: 1px solid #FF75C8;
}
QToolButton#icon_mic:hover, QToolButton#icon_mic:checked {
    background: rgba(135,35,103,0.82);
    border: 1px solid #FFD1F0;
}
QToolButton#icon_moon {
    background: rgba(45,30,84,0.88);
    border: 1px solid #A98AFF;
}
QToolButton#icon_moon:hover, QToolButton#icon_moon:checked {
    background: rgba(87,54,145,0.84);
    border: 1px solid #E0D0FF;
}
QToolButton#icon_speaker {
    background: rgba(16,54,78,0.90);
    border: 1px solid #55E9FF;
}
QToolButton#icon_speaker:hover, QToolButton#icon_speaker:checked {
    background: rgba(21,112,145,0.82);
    border: 1px solid #C6FBFF;
}
QToolButton#icon_stop {
    background: rgba(73,28,59,0.90);
    border: 1px solid #FF85B8;
}
QToolButton#icon_stop:hover {
    background: rgba(145,35,83,0.88);
    border: 1px solid #FFD4E5;
}
QToolButton#sendBtn {
    border: 1px solid #E5FDFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #00DFFF, stop:0.48 #477DFF, stop:1 #B45CFF);
}
QToolButton#sendBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #86F4FF, stop:0.48 #83A8FF, stop:1 #D69AFF);
    border: 1px solid #FFFFFF;
}
QToolButton#routeChip {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #103C56, stop:1 #33245F);
    border: 1px solid #53E8FF;
}
QToolButton#routeChip:hover { border: 1px solid #FFFFFF; }

/* Brighter focus rings make text and setting controls feel connected to the neon theme. */
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #67EDFF;
}
QGroupBox {
    border: 1px solid rgba(100,205,255,0.52);
    background: rgba(15,25,49,0.94);
}
QGroupBox::title { color: #C4AEFF; }

"""

# Only background tokens are replaced, so text and icon colors remain untouched.
GLASS_TINTS = {
    "#172744": "rgba(23,39,68,0.48)",
    "#121B32": "rgba(18,27,50,0.52)",
    "#111A31": "rgba(15,22,42,0.58)",
    "#202448": "rgba(32,36,72,0.62)",
    "#121C32": "rgba(15,24,43,0.64)",
    "#192747": "rgba(25,39,71,0.56)",
}

# Popups are kept opaque for legibility; DWM backdrop effects apply to the main window.
GLASS_OPAQUE = """
QDialog, QMessageBox, QFileDialog { background: #10172A; color: #EAF2FF; }
QMenu { background: #111A31; color: #EAF2FF; }
QToolTip { background: #111A31; color: #F0F6FF; }
QComboBox QAbstractItemView { background: #111A31; color: #EAF2FF; }
QDialog QListWidget { background: #121C32; }
"""


def build_style(effect="off"):
    """Return the neon stylesheet for 'off', 'mica', or 'acrylic'."""
    if effect not in ("mica", "acrylic"):
        return STYLE
    alpha = "0.34" if effect == "acrylic" else "0.62"
    css = STYLE.replace(
        "QMainWindow { background: #0A0F20; }",
        f"QMainWindow {{ background: rgba(7,10,22,{alpha}); }}",
        1,
    )
    for opaque, tint in GLASS_TINTS.items():
        css = css.replace(opaque, tint)
    return css + "\n" + GLASS_OPAQUE
