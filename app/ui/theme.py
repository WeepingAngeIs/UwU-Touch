"""Nova themes: neon night (dark) and sakura (light)."""

PALETTES = {
    "dark": {
        "bg": "#140b1f", "bg2": "#2a0f33", "panel": "rgba(26, 13, 38, 228)", "panel_solid": "#1d0f2b",
        "panel2": "rgba(44, 20, 60, 235)", "border": "#6e2a66", "border_soft": "#3d1d4c",
        "text": "#f6e9ff", "muted": "#b9a3c9", "title": "#ffe3f4",
        "accent": "#ff3d9a", "accent2": "#ff70b8", "accent_text": "#ffffff",
        "violet": "#7b3cf0", "violet2": "#9b6bff",
        "danger": "#ff3d6e", "ok": "#2bd47a", "info": "#4f86ff", "select": "rgba(255, 61, 154, 120)",
        "input": "rgba(14, 7, 22, 230)", "hover": "rgba(255, 61, 154, 40)",
        "blossom": "#ff7ac3", "blossom2": "#c33cff",
    },
    "light": {
        "bg": "#fff2f8", "bg2": "#fbd9ec", "panel": "rgba(255, 255, 255, 235)", "panel_solid": "#ffffff",
        "panel2": "rgba(255, 240, 248, 240)", "border": "#f0a6cf", "border_soft": "#f6cfe3",
        "text": "#35142c", "muted": "#8a5c7a", "title": "#5a1342",
        "accent": "#e6338a", "accent2": "#ff6fb0", "accent_text": "#ffffff",
        "violet": "#7b3cf0", "violet2": "#9b6bff",
        "danger": "#e0245e", "ok": "#18a35d", "info": "#2f6fd6", "select": "rgba(230, 51, 138, 70)",
        "input": "#ffffff", "hover": "rgba(230, 51, 138, 25)",
        "blossom": "#ff9fcf", "blossom2": "#e9a8ff",
    },
}


def stylesheet(name: str) -> str:
    c = PALETTES.get(name, PALETTES["dark"])
    grad = lambda a, b: f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {a}, stop:1 {b})"
    return f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['panel_solid']}; }}
QWidget {{ background: transparent; }}
QDialog QWidget {{ background: transparent; }}
QLabel#h1 {{ font-size: 17pt; font-weight: 700; color: {c['title']}; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 700; color: {c['title']}; }}
QLabel#brand {{ font-family: "Segoe Script", "Segoe Print", "Comic Sans MS", cursive; font-size: 19pt; font-weight: 700; color: {c['text']}; }}
QLabel#script {{ font-family: "Segoe Script", "Segoe Print", "Comic Sans MS", cursive; font-size: 15pt; color: {c['text']}; }}
QLabel#muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
QLabel#bigclock {{ font-size: 24pt; font-weight: 600; font-family: "Consolas", "Cascadia Mono", monospace; color: {c['title']}; }}
QLabel#stat {{ font-size: 18pt; font-weight: 700; }}
QLabel#tilestate {{ font-weight: 600; }}
QFrame#card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#tile {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#tile[state="ok"] {{ border: 1px solid {c['ok']}; }}
QFrame#tile[state="rec"] {{ border: 1px solid {c['danger']}; }}
QFrame#tile[state="info"] {{ border: 1px solid {c['info']}; }}
QFrame#header, QFrame#footer {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#chip {{ background: {c['panel2']}; border: 1px solid {c['border_soft']}; border-radius: 8px; }}
QPushButton#tab {{ background: {c['panel2']}; border: 1px solid {c['border_soft']}; border-radius: 9px;
    padding: 8px 11px; font-weight: 600; }}
QPushButton#tab:hover {{ border: 1px solid {c['accent']}; }}
QPushButton#tab:checked {{ background: {grad(c['accent2'], c['accent'])}; color: white; border: 1px solid {c['accent2']}; }}
QPushButton {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 13px; }}
QPushButton:hover {{ border: 1px solid {c['accent']}; background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['select']}; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border_soft']}; }}
QPushButton[kind="primary"] {{ background: {grad(c['accent2'], c['accent'])}; color: white; border: 1px solid {c['accent2']}; font-weight: 700; }}
QPushButton[kind="primary"]:hover {{ border: 1px solid white; }}
QPushButton[kind="primary"]:disabled {{ background: {c['panel2']}; color: {c['muted']}; border-color: {c['border_soft']}; }}
QPushButton[kind="violet"] {{ background: {grad(c['violet2'], c['violet'])}; color: white; border: 1px solid {c['violet2']}; font-weight: 700; }}
QPushButton[kind="violet"]:hover {{ border: 1px solid white; }}
QPushButton[kind="violet"]:disabled {{ background: {c['panel2']}; color: {c['muted']}; border-color: {c['border_soft']}; }}
QPushButton[kind="danger"] {{ background: {grad('#ff6b8f', c['danger'])}; color: white; border: 1px solid #ff8fab; font-weight: 700; }}
QPushButton[kind="danger"]:hover {{ border: 1px solid white; }}
QPushButton[kind="danger"]:disabled {{ background: {c['panel2']}; color: {c['muted']}; border-color: {c['border_soft']}; }}
QPushButton[kind="big"] {{ padding: 11px 20px; font-size: 11pt; font-weight: 700; }}
QPushButton[size="big"] {{ padding: 11px 20px; font-size: 11.5pt; min-width: 90px; }}
QPushButton[kind="qa_rec"] {{ background: {grad('#ff5f86', '#c81e4f')}; border: 1px solid #ff8fab; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QPushButton[kind="qa_play"] {{ background: {grad('#3be58b', '#139a54')}; border: 1px solid #7ef0b0; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QPushButton[kind="qa_stop"] {{ background: {grad('#ff5fae', '#c4237a')}; border: 1px solid #ff9ccc; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QPushButton[kind="qa_blue"] {{ background: {grad('#3d7bff', '#1d47b8')}; border: 1px solid #7ea6ff; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QPushButton[kind="qa_violet"] {{ background: {grad('#7d4dff', '#4a22b5')}; border: 1px solid #a98bff; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QPushButton[kind="qa_indigo"] {{ background: {grad('#5a3fd6', '#2e1c80')}; border: 1px solid #8f7cf0; color: white; font-weight: 600; border-radius: 10px; padding: 4px; font-size: 9.5pt; }}
QToolButton {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 5px 10px; }}
QToolButton:hover {{ border: 1px solid {c['accent']}; background: {c['hover']}; }}
QToolButton:disabled {{ color: {c['muted']}; border-color: {c['border_soft']}; }}
QToolButton::menu-indicator {{ image: none; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit, QDateTimeEdit {{
    background: {c['input']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 5px 7px;
    selection-background-color: {c['accent']}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTimeEdit:focus, QDateTimeEdit:focus {{ border: 1px solid {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['panel_solid']}; border: 1px solid {c['border']};
    selection-background-color: {c['select']}; selection-color: {c['text']}; }}
QTableView, QTableWidget, QListWidget, QTreeWidget {{ background: {c['input']}; alternate-background-color: {c['panel2']};
    border: 1px solid {c['border_soft']}; border-radius: 8px; gridline-color: {c['border_soft']};
    selection-background-color: {c['select']}; selection-color: {c['text']}; }}
QTableView::item:selected {{ border-top: 1px solid {c['accent']}; border-bottom: 1px solid {c['accent']}; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; padding: 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['panel2']}; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {c['panel2']}; padding: 6px 14px; margin-right: 4px; color: {c['muted']};
    border: 1px solid {c['border_soft']}; border-radius: 7px; }}
QTabBar::tab:selected {{ color: white; background: {grad(c['accent2'], c['accent'])}; border-color: {c['accent2']}; font-weight: 600; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px; background: {c['panel']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {c['muted']}; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {c['border']}; border-radius: 4px; background: {c['input']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent2']}; }}
QRadioButton::indicator {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['input']}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 white, stop:0.35 white, stop:0.45 {c['accent']}, stop:1 {c['accent']}); border: 1px solid {c['accent2']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['border_soft']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {grad(c['accent2'], c['accent'])}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {c['accent2']}; border: 2px solid white; width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }}
QProgressBar {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 7px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {grad(c['accent2'], c['accent'])}; border-radius: 6px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}
QMenu {{ background: {c['panel_solid']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['select']}; }}
QToolTip {{ background: {c['panel_solid']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
QLabel#pill {{ border-radius: 10px; padding: 3px 10px; font-weight: 600; background: {c['panel2']}; color: {c['muted']}; }}
QLabel#pill[state="rec"] {{ background: {c['danger']}; color: white; }}
QLabel#pill[state="play"] {{ background: {c['ok']}; color: white; }}
QLabel#pill[state="sched"] {{ background: {c['info']}; color: white; }}
QLabel#pill[state="warn"] {{ background: {c['accent']}; color: white; }}
QLabel#hk {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 14px; font-weight: 600; }}
"""


def color(name: str, key: str) -> str:
    return PALETTES.get(name, PALETTES["dark"])[key]
