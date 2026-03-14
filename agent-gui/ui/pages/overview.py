"""NOCKO Agent — Overview Page (All modules summary)"""
import platform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

BRAND = {
    "bg": "#0f0f1a", "card": "#1a1a2e", "accent": "#2563eb",
    "text": "#e2e8f0", "muted": "#94a3b8", "border": "#1e293b",
    "success": "#10b981", "warning": "#f59e0b", "danger": "#ef4444",
}

CARD_STYLE = f"""
    QFrame#card {{
        background-color: {BRAND['card']};
        border: 1px solid {BRAND['border']};
        border-radius: 12px;
    }}
"""


def status_color(status: str) -> str:
    s = status.lower()
    if "online" in s or "running" in s:
        return BRAND["success"]
    elif "coming" in s or "stub" in s or "disabled" in s:
        return BRAND["warning"]
    elif "offline" in s or "error" in s or "failed" in s:
        return BRAND["danger"]
    return BRAND["muted"]


class ModuleCard(QFrame):
    def __init__(self, icon: str, name: str, desc: str, status: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(CARD_STYLE)
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 22))
        self.name_lbl = QLabel(name)
        self.name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.name_lbl.setStyleSheet(f"color: {BRAND['text']};")
        top.addWidget(icon_lbl)
        top.addWidget(self.name_lbl)
        top.addStretch()
        layout.addLayout(top)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {BRAND['muted']}; font-size: 12px;")
        layout.addWidget(desc_lbl)

        self.status_dot  = QLabel("●")
        self.status_text = QLabel(status)
        self.status_text.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self._update_status_color(status)

        st_row = QHBoxLayout()
        st_row.addWidget(self.status_dot)
        st_row.addWidget(self.status_text)
        st_row.addStretch()
        layout.addLayout(st_row)

    def set_status(self, status: str):
        self.status_text.setText(status)
        self._update_status_color(status)

    def _update_status_color(self, status: str):
        c = status_color(status)
        self.status_dot.setStyleSheet(f"color: {c}; font-size: 10px;")
        self.status_text.setStyleSheet(f"color: {c};")


class OverviewPage(QWidget):
    def __init__(self, mdm=None, siem=None, backup=None, remote=None, parent=None):
        super().__init__(parent)
        self._mdm    = mdm
        self._siem   = siem
        self._backup = backup
        self._remote = remote

        self.setStyleSheet(f"background-color: {BRAND['bg']}; color: {BRAND['text']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        # Header
        hdr = QLabel("Agent Overview")
        hdr.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        sub = QLabel(f"Host: {platform.node()}  •  Platform: {platform.system()}")
        sub.setStyleSheet(f"color: {BRAND['muted']}; font-size: 12px;")
        layout.addWidget(hdr)
        layout.addWidget(sub)

        # Module cards grid
        grid = QGridLayout()
        grid.setSpacing(16)

        self._mdm_card    = ModuleCard("🖥", "MDM",           "Device management & commands", "Initializing...")
        self._siem_card   = ModuleCard("🛡", "SIEM",          "Windows event monitoring",      "Initializing...")
        self._backup_card = ModuleCard("💾", "Backup",        "File sync & backup",            "Coming soon")
        self._remote_card = ModuleCard("🖱", "Remote Access", "AnyDesk-style remote desktop",  "Coming soon")

        grid.addWidget(self._mdm_card,    0, 0)
        grid.addWidget(self._siem_card,   0, 1)
        grid.addWidget(self._backup_card, 1, 0)
        grid.addWidget(self._remote_card, 1, 1)
        layout.addLayout(grid)

        # System info strip
        info_card = QFrame()
        info_card.setObjectName("card")
        info_card.setStyleSheet(CARD_STYLE)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 16, 20, 16)
        info_lbl = QLabel("📋  System Information")
        info_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        info_layout.addWidget(info_lbl)

        sys_info = (
            f"OS: {platform.system()} {platform.version()[:60]}\n"
            f"Hostname: {platform.node()}\n"
            f"Machine: {platform.machine()}  •  Processor: {platform.processor()[:50] or 'N/A'}"
        )
        sys_lbl = QLabel(sys_info)
        sys_lbl.setStyleSheet(f"color: {BRAND['muted']}; font-size: 12px;")
        sys_lbl.setWordWrap(True)
        info_layout.addWidget(sys_lbl)
        layout.addWidget(info_card)

        layout.addStretch()

        # Auto-refresh every 10s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(10000)
        self._refresh()

    def _refresh(self):
        if self._mdm:
            mdm_status = getattr(self._mdm, '_last_status', 'Initializing...')
            # Fallback to checking last_checkin
            if hasattr(self._mdm, 'last_checkin') and self._mdm.last_checkin:
                mdm_status = f"Online • Last: {self._mdm.last_checkin}"
            self._mdm_card.set_status(mdm_status)
        if self._siem:
            cnt = len(getattr(self._siem, 'event_buffer', []))
            self._siem_card.set_status(f"Running • {cnt} events buffered")
