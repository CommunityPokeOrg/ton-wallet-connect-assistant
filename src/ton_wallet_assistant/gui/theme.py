"""Dark stylesheet approximating the Tonkeeper desktop look."""

ACCENT = "#45AEF5"
BG = "#10161E"
PANEL = "#1D2633"
PANEL_ALT = "#232D3C"
TEXT = "#E7ECEF"
TEXT_DIM = "#9AA6B2"
BORDER = "#2E3A48"
DANGER = "#E74C3C"
WARNING = "#F0A020"
SUCCESS = "#39D98A"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Ubuntu", "Noto Sans", sans-serif;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background: {BG};
}}
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    color: {TEXT_DIM};
}}
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {BORDER}; }}
QPushButton:pressed {{ background: {ACCENT}; color: #0b1016; }}
QPushButton:disabled {{ color: {TEXT_DIM}; }}
QPushButton#primary {{
    background: {ACCENT};
    color: #0b1016;
    font-weight: bold;
    border: none;
}}
QPushButton#primary:hover {{ background: #6cc2f7; }}
QLineEdit, QPlainTextEdit, QComboBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[readOnly="true"] {{ color: {TEXT_DIM}; }}
QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 6px;
}}
QListWidget::item:selected {{ background: {PANEL_ALT}; color: {ACCENT}; }}
QListWidget::item:hover {{ background: {PANEL_ALT}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    padding: 8px 18px;
    color: {TEXT_DIM};
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {BORDER}; }}
QDialog {{ background: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QCheckBox {{ spacing: 8px; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {PANEL_ALT};
}}
/* Sidebar navigation */
QListWidget#sidebar {{
    background: {BG};
    border: none;
    border-right: 1px solid {BORDER};
}}
QListWidget#sidebar::item {{
    padding: 12px 16px;
    border-radius: 8px;
    margin: 2px 8px;
    color: {TEXT_DIM};
    font-weight: 600;
}}
QListWidget#sidebar::item:selected {{ background: {PANEL_ALT}; color: {ACCENT}; }}
QListWidget#sidebar::item:hover {{ color: {TEXT}; background: {PANEL}; }}
QLabel#balance {{ font-size: 34px; font-weight: 800; }}
QLabel#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
"""
