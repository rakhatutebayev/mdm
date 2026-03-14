"""
NOCKO Unified Agent — Main Entry Point
Starts background modules and shows the system tray icon.
"""
import sys
import os

# Ensure agent-gui root is in path when run from any CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from logger import setup_logging, get_logger
from config import config
from modules.mdm    import MDMModule
from modules.siem   import SIEMModule
from modules.backup import BackupModule
from modules.remote import RemoteModule
from ui.tray        import TrayIcon
from ui.main_window import MainWindow

log = get_logger("main")


def main():
    setup_logging(config.get("log_level", "INFO"))
    log.info(f"NOCKO Agent v{config.agent_version} starting...")

    # Qt requires a QApplication before any widgets
    app = QApplication(sys.argv)
    app.setApplicationName("NOCKO Agent")
    app.setApplicationVersion(config.agent_version)
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray

    # Apply global dark palette
    app.setStyle("Fusion")

    if not QApplication.instance().platformName() in ("windows", "xcb", "cocoa", "offscreen"):
        log.warning("Unknown Qt platform, continuing anyway")

    # Check tray is available
    from PyQt6.QtWidgets import QSystemTrayIcon
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "NOCKO Agent",
                             "System tray not available on this system.\n"
                             "Please run on a desktop with a taskbar.")
        sys.exit(1)

    # ── Instantiate modules ──────────────────────────────────────────────
    mdm_module    = MDMModule()
    siem_module   = SIEMModule()
    backup_module = BackupModule()
    remote_module = RemoteModule()

    # ── Main window ──────────────────────────────────────────────────────
    window = MainWindow(
        mdm_module    = mdm_module,
        siem_module   = siem_module,
        backup_module = backup_module,
        remote_module = remote_module,
    )

    # ── Tray icon ────────────────────────────────────────────────────────
    tray = TrayIcon()
    tray.open_dashboard_requested.connect(window.show)
    tray.open_dashboard_requested.connect(window.raise_)
    tray.open_dashboard_requested.connect(window.activateWindow)
    tray.checkin_requested.connect(mdm_module.checkin_now)
    tray.quit_requested.connect(lambda: _quit(app, mdm_module, siem_module))

    # MDM status → tray icon color
    def _on_mdm_status(status: str):
        tray.set_status_icon("online" in status.lower())
        tray.show_notification("NOCKO Agent", f"MDM: {status}", ms=2000)

    mdm_module.on_status_change = _on_mdm_status

    # ── Start background modules ─────────────────────────────────────────
    # Use QTimer to start after event loop is live
    QTimer.singleShot(500,  mdm_module.start)
    QTimer.singleShot(1500, siem_module.start)

    # Show dashboard on first launch (no token set)
    if not config.enrollment_token:
        QTimer.singleShot(800, window.show)
        tray.show_notification(
            "NOCKO Agent",
            "Welcome! Open Dashboard → Settings to enter your enrollment token.",
            ms=5000,
        )

    log.info("NOCKO Agent running in system tray")
    sys.exit(app.exec())


def _quit(app: QApplication, mdm, siem):
    log.info("NOCKO Agent shutting down...")
    mdm.stop()
    siem.stop()
    app.quit()


if __name__ == "__main__":
    main()
