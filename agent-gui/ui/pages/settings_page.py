"""NOCKO Agent — Settings Page"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QSpinBox, QFrame, QFormLayout,
    QGroupBox, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from config import config
from logger import get_logger

log = get_logger("settings")

BRAND = {
    "bg": "#0f0f1a", "card": "#1a1a2e", "accent": "#2563eb",
    "accent_hover": "#1d4ed8", "text": "#e2e8f0", "muted": "#94a3b8",
    "border": "#1e293b", "success": "#10b981",
}

INPUT = f"""
QLineEdit, QSpinBox {{
    background: #0f0f1a; color: {BRAND['text']};
    border: 1px solid {BRAND['border']}; border-radius: 8px;
    padding: 8px 12px; font-size: 13px;
}}
QLineEdit:focus, QSpinBox:focus {{
    border-color: {BRAND['accent']};
}}
QCheckBox {{ color: {BRAND['text']}; font-size: 13px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 2px solid {BRAND['border']}; border-radius: 4px;
    background: {BRAND['card']};
}}
QCheckBox::indicator:checked {{
    background: {BRAND['accent']};
    border-color: {BRAND['accent']};
}}
"""

CARD = f"""
QGroupBox {{
    background: {BRAND['card']}; border: 1px solid {BRAND['border']};
    border-radius: 12px; margin-top: 12px;
    font-size: 13px; font-weight: 600; color: {BRAND['text']};
    padding: 14px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px;
    padding: 0 6px;
}}
"""

BTN = f"""
QPushButton {{
    background: {BRAND['accent']}; color: white;
    border: none; padding: 10px 28px;
    border-radius: 8px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background: {BRAND['accent_hover']}; }}
"""


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BRAND['bg']}; color: {BRAND['text']};" + INPUT + CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        hdr = QLabel("Settings")
        hdr.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        layout.addWidget(hdr)

        # ── MDM Settings ──────────────────────────────────────────────────
        mdm_grp = QGroupBox("MDM Connection")
        mdm_layout = QFormLayout(mdm_grp)
        mdm_layout.setSpacing(12)

        self._host_edit = QLineEdit(config.server_host)
        self._host_edit.setPlaceholderText("mdm.it-uae.com")

        self._scheme_combo = QLineEdit(config.server_scheme)
        self._scheme_combo.setPlaceholderText("https")

        self._api_prefix_edit = QLineEdit(config.api_prefix)
        self._api_prefix_edit.setPlaceholderText("/api/v1")

        # Live preview of the full assembled URL
        self._url_preview = QLabel(f"{config.mdm_server}")
        self._url_preview.setStyleSheet(
            f"color: {BRAND['muted']}; font-size: 11px; font-family: monospace;"
        )
        for edit in (self._host_edit, self._scheme_combo, self._api_prefix_edit):
            edit.textChanged.connect(self._update_url_preview)

        self._token_edit = QLineEdit(config.enrollment_token)
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setPlaceholderText("Enrollment token from MDM console")
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setValue(config.checkin_interval)
        self._interval_spin.setSuffix(" min")

        mdm_layout.addRow("Server Host:",   self._host_edit)
        mdm_layout.addRow("Scheme:",         self._scheme_combo)
        mdm_layout.addRow("API Prefix:",     self._api_prefix_edit)
        mdm_layout.addRow("Full URL preview:", self._url_preview)
        mdm_layout.addRow("Enrollment Token:", self._token_edit)
        mdm_layout.addRow("Check-in Interval:", self._interval_spin)
        layout.addWidget(mdm_grp)

        # ── Module Toggles ────────────────────────────────────────────────
        mod_grp = QGroupBox("Module Settings")
        mod_layout = QFormLayout(mod_grp)
        mod_layout.setSpacing(12)

        self._siem_check   = QCheckBox("Enable SIEM event collection")
        self._siem_check.setChecked(config.siem_enabled)
        self._siem_interval = QSpinBox()
        self._siem_interval.setRange(1, 60)
        self._siem_interval.setValue(config.siem_interval)
        self._siem_interval.setSuffix(" min")

        self._backup_check = QCheckBox("Enable Backup (Coming in v2)")
        self._backup_check.setChecked(config.backup_enabled)
        self._backup_check.setEnabled(False)

        self._remote_check = QCheckBox("Enable Remote Access (Coming in v2)")
        self._remote_check.setChecked(config.remote_enabled)
        self._remote_check.setEnabled(False)

        mod_layout.addRow(self._siem_check)
        mod_layout.addRow("SIEM Collect Interval:", self._siem_interval)
        mod_layout.addRow(self._backup_check)
        mod_layout.addRow(self._remote_check)
        layout.addWidget(mod_grp)

        # ── Save button ───────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setStyleSheet(BTN)
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        layout.addStretch()

    def _build_url_preview(self) -> str:
        scheme = self._scheme_combo.text().strip() or "https"
        host   = self._host_edit.text().strip() or "<host>"
        prefix = self._api_prefix_edit.text().strip() or "/api/v1"
        return f"{scheme}://{host}{prefix}"

    def _update_url_preview(self):
        self._url_preview.setText(self._build_url_preview())

    def _save(self):
        config.set("server_host",       self._host_edit.text().strip())
        config.set("server_scheme",     self._scheme_combo.text().strip() or "https")
        config.set("api_prefix",        self._api_prefix_edit.text().strip() or "/api/v1")
        config.set("enrollment_token",  self._token_edit.text().strip())
        config.set("checkin_interval",  self._interval_spin.value())
        config.set("siem_enabled",      self._siem_check.isChecked())
        config.set("siem_interval",     self._siem_interval.value())
        config.save()
        log.info("Settings saved")

        mb = QMessageBox(self)
        mb.setWindowTitle("Saved")
        mb.setText("✅  Settings saved successfully.\nRestart the agent for changes to take effect.")
        mb.setStyleSheet(f"background: {BRAND['card']}; color: {BRAND['text']};")
        mb.exec()
