"""
NOCKO Agent — System Tray Icon
"""
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject, pyqtSignal

from logger import get_logger

log = get_logger("tray")


class TrayIcon(QObject):
    open_dashboard_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    checkin_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(QIcon("ui/assets/nocko.png"))
        self._tray.setToolTip("NOCKO Agent")
        self._build_menu()
        self._tray.activated.connect(self._on_activate)
        self._tray.show()

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a2e;
                color: #e2e8f0;
                border: 1px solid #2d3748;
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                border-radius: 4px;
            }
            QMenu::separator {
                height: 1px;
                background: #2d3748;
                margin: 4px 0;
            }
        """)

        open_action = QAction("🖥  Open Dashboard", menu)
        open_action.triggered.connect(self.open_dashboard_requested.emit)
        menu.addAction(open_action)

        menu.addSeparator()

        checkin_action = QAction("🔄  Check-in Now", menu)
        checkin_action.triggered.connect(self.checkin_requested.emit)
        menu.addAction(checkin_action)

        menu.addSeparator()

        quit_action = QAction("✖  Quit Agent", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_dashboard_requested.emit()

    def show_notification(self, title: str, message: str,
                          icon=QSystemTrayIcon.MessageIcon.Information, ms: int = 3000):
        self._tray.showMessage(title, message, icon, ms)

    def set_status_icon(self, online: bool):
        icon = "ui/assets/nocko_online.png" if online else "ui/assets/nocko_offline.png"
        self._tray.setIcon(QIcon(icon))
        self._tray.setToolTip(f"NOCKO Agent — {'Online' if online else 'Offline'}")
