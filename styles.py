"""Thèmes Dark / Light (QSS)."""
from string import Template

PALETTES = {
    "dark": dict(bg="#12161c", panel="#1b212a", panel2="#242c38", text="#e8edf3", muted="#8b97a7",
                 accent="#2f80ed", border="#2c3644", input="#151a21"),
    "light": dict(bg="#f3f5f8", panel="#ffffff", panel2="#eef1f5", text="#1b2430", muted="#5f6b7a",
                  accent="#1f6feb", border="#d5dbe3", input="#ffffff"),
}
TRIAGE_COLORS = {"ROUGE": "#e74c3c", "ORANGE": "#f39c12", "VERT": "#2ecc71"}
TRIAGE_ICON = {"ROUGE": "🔴", "ORANGE": "🟠", "VERT": "🟢"}
TRIAGE_TEXT = {"ROUGE": "Urgence absolue", "ORANGE": "Urgence relative", "VERT": "Urgence ordinaire"}

_QSS = Template("""
QWidget { background:$bg; color:$text; font-family:'Segoe UI','Noto Sans',sans-serif; font-size:14px; }
QLabel, QCheckBox, QRadioButton { background:transparent; }
QFrame#card { background:$panel; border:1px solid $border; border-radius:12px; }
QGroupBox { background:$panel; border:1px solid $border; border-radius:10px; margin-top:16px; padding:12px 8px 8px 8px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:$muted; }
QLineEdit, QComboBox, QSpinBox { background:$input; border:1px solid $border; border-radius:8px; padding:8px; min-height:22px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border:1px solid $accent; }
QComboBox QAbstractItemView { background:$panel; selection-background-color:$accent; }
QPushButton { background:$panel2; border:1px solid $border; border-radius:8px; padding:9px 16px; }
QPushButton:hover { border-color:$accent; }
QPushButton:checked { background:$accent; color:white; border-color:$accent; font-weight:600; }
QPushButton#primary { background:$accent; color:white; font-weight:700; border:none; padding:14px 20px; font-size:16px; }
QPushButton#danger { background:#c0392b; color:white; border:none; }
QPushButton[service="true"] { text-align:left; padding:12px; font-size:15px; }
QTableWidget { background:$panel; alternate-background-color:$panel2; gridline-color:$border; border:1px solid $border; border-radius:8px; selection-background-color:$accent; selection-color:white; }
QHeaderView::section { background:$panel2; padding:6px; border:none; color:$muted; font-weight:600; }
QTabWidget::pane { border:1px solid $border; border-radius:8px; }
QTabBar::tab { padding:9px 16px; background:$panel2; border-radius:6px; margin-right:4px; }
QTabBar::tab:selected { background:$accent; color:white; }
QScrollArea { border:none; }
""")


def stylesheet(theme):
    return _QSS.substitute(PALETTES.get(theme, PALETTES["dark"]))
