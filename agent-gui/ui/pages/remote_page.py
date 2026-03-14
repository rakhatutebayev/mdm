"""NOCKO Agent — Remote Access Page (Stub UI)"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

BRAND = {"bg": "#0f0f1a", "card": "#1a1a2e", "text": "#e2e8f0",
         "muted": "#94a3b8", "border": "#1e293b", "warning": "#f59e0b"}


class RemotePage(QWidget):
    def __init__(self, remote_module=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BRAND['bg']}; color: {BRAND['text']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        hdr = QLabel("Remote Access")
        hdr.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        layout.addWidget(hdr)

        card = QFrame()
        card.setStyleSheet(f"""QFrame {{
            background: {BRAND['card']}; border: 1px solid {BRAND['border']};
            border-radius: 16px;
        }}""")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 50, 40, 50)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🖥")
        icon.setFont(QFont("Segoe UI Emoji", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Coming in v2")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {BRAND['warning']};")

        desc = QLabel(
            "The Remote Access module will provide AnyDesk-style remote desktop\n"
            "over a secure WebSocket tunnel — no VPN or port forwarding required.\n\n"
            "IT administrators will be able to connect from the NOCKO MDM console."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {BRAND['muted']}; font-size: 13px;")

        roadmap = QLabel("📋  Roadmap: Screen capture → Input injection → WebRTC tunnel → Session auth")
        roadmap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        roadmap.setStyleSheet(f"color: {BRAND['muted']}; font-size: 11px;")

        for w in (icon, title, desc, roadmap):
            card_layout.addWidget(w)

        layout.addWidget(card)
