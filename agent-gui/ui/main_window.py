"""
NOCKO Agent — Main Dashboard Window
Dark theme, left sidebar navigation, animated status cards.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap

from ui.pages.overview    import OverviewPage
from ui.pages.mdm_page    import MDMPage
from ui.pages.siem_page   import SIEMPage
from ui.pages.backup_page import BackupPage
from ui.pages.remote_page import RemotePage
from ui.pages.settings_page import SettingsPage

BRAND = {
    "bg":           "#0f0f1a",
    "sidebar":      "#13131f",
    "card":         "#1a1a2e",
    "accent":       "#2563eb",
    "accent_hover": "#1d4ed8",
    "text":         "#e2e8f0",
    "muted":        "#94a3b8",
    "border":       "#1e293b",
    "success":      "#10b981",
    "warning":      "#f59e0b",
    "danger":       "#ef4444",
}

STYLE = f"""
QMainWindow, QWidget#root {{
    background-color: {BRAND['bg']};
    color: {BRAND['text']};
    font-family: 'Segoe UI', 'Inter', sans-serif;
}}
QWidget#sidebar {{
    background-color: {BRAND['sidebar']};
    border-right: 1px solid {BRAND['border']};
}}
QPushButton#nav_btn {{
    background: transparent;
    color: {BRAND['muted']};
    text-align: left;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13px;
    border: none;
}}
QPushButton#nav_btn:hover {{
    background-color: rgba(37,99,235,0.15);
    color: {BRAND['text']};
}}
QPushButton#nav_btn:checked {{
    background-color: rgba(37,99,235,0.25);
    color: {BRAND['accent']};
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: {BRAND['border']};
    border-radius: 3px;
}}
"""

NAV_ITEMS = [
    ("🏠", "Overview",      OverviewPage),
    ("🖥", "MDM",           MDMPage),
    ("🛡", "SIEM",          SIEMPage),
    ("💾", "Backup",        BackupPage),
    ("🖱", "Remote Access", RemotePage),
    ("⚙", "Settings",      SettingsPage),
]


class SidebarButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("nav_btn")
        self.setText(f"  {icon}  {label}")
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class MainWindow(QMainWindow):
    def __init__(self, mdm_module=None, siem_module=None,
                 backup_module=None, remote_module=None):
        super().__init__()
        self.setWindowTitle("NOCKO Agent")
        self.setMinimumSize(1000, 660)
        self.resize(1120, 700)

        self._mdm    = mdm_module
        self._siem   = siem_module
        self._backup = backup_module
        self._remote = remote_module

        self.setStyleSheet(STYLE)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 16, 12, 16)
        sb_layout.setSpacing(4)

        # Logo
        logo_label = QLabel("NOCKO")
        logo_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        logo_label.setStyleSheet(f"color: {BRAND['accent']}; letter-spacing: 2px;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setFixedHeight(48)
        sb_layout.addWidget(logo_label)

        sub_label = QLabel("Unified Agent")
        sub_label.setFont(QFont("Segoe UI", 9))
        sub_label.setStyleSheet(f"color: {BRAND['muted']};")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(sub_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BRAND['border']};")
        sb_layout.addWidget(sep)
        sb_layout.addSpacing(8)

        # Nav buttons
        self._stack   = QStackedWidget()
        self._nav_btns: list[SidebarButton] = []
        self._pages: list[QWidget] = []

        for idx, (icon, label, PageClass) in enumerate(NAV_ITEMS):
            btn = SidebarButton(icon, label)
            sb_layout.addWidget(btn)
            self._nav_btns.append(btn)

            # Instantiate page with relevant module
            page = self._create_page(PageClass)
            self._stack.addWidget(page)
            self._pages.append(page)

            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))

        sb_layout.addStretch()

        # Version label
        ver = QLabel("v1.0.0")
        ver.setStyleSheet(f"color: {BRAND['muted']}; font-size: 11px;")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(ver)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self._stack, 1)

        self._switch_page(0)

    def _create_page(self, PageClass):
        try:
            if PageClass == MDMPage:
                return MDMPage(mdm_module=self._mdm)
            elif PageClass == SIEMPage:
                return SIEMPage(siem_module=self._siem)
            elif PageClass == BackupPage:
                return BackupPage(backup_module=self._backup)
            elif PageClass == RemotePage:
                return RemotePage(remote_module=self._remote)
            elif PageClass == OverviewPage:
                return OverviewPage(mdm=self._mdm, siem=self._siem,
                                   backup=self._backup, remote=self._remote)
            else:
                return PageClass()
        except Exception as e:
            err = QLabel(f"Failed to load page: {e}")
            err.setStyleSheet(f"color: {BRAND['danger']}; padding: 20px;")
            return err

    def _switch_page(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)

    def closeEvent(self, event):
        # Minimize to tray instead of closing
        event.ignore()
        self.hide()
