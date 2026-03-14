"""NOCKO Agent — MDM Page"""
import platform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QColor

BRAND = {
    "bg": "#0f0f1a", "card": "#1a1a2e", "accent": "#2563eb",
    "accent_hover": "#1d4ed8", "text": "#e2e8f0", "muted": "#94a3b8",
    "border": "#1e293b", "success": "#10b981", "warning": "#f59e0b",
    "danger": "#ef4444",
}

CARD = f"QFrame#card {{ background: {BRAND['card']}; border: 1px solid {BRAND['border']}; border-radius: 12px; }}"
BTN  = f"""QPushButton {{
    background: {BRAND['accent']}; color: white; border: none;
    padding: 9px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ background: {BRAND['accent_hover']}; }}
QPushButton:disabled {{ background: {BRAND['border']}; color: {BRAND['muted']}; }}
"""
TABLE = f"""QTableWidget {{
    background: transparent; color: {BRAND['text']};
    gridline-color: {BRAND['border']}; border: none; font-size: 12px;
}}
QHeaderView::section {{
    background: {BRAND['card']}; color: {BRAND['muted']};
    border: none; padding: 8px; font-size: 11px; text-transform: uppercase;
}}
QTableWidget::item:selected {{ background: rgba(37,99,235,0.25); }}
"""


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        self.val_lbl  = QLabel(value)
        self.val_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.val_lbl.setStyleSheet(f"color: {BRAND['text']};")
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {BRAND['muted']}; font-size: 11px;")
        layout.addWidget(self.val_lbl)
        layout.addWidget(lbl)

    def set_value(self, v: str):
        self.val_lbl.setText(v)


class MDMPage(QWidget):
    def __init__(self, mdm_module=None, parent=None):
        super().__init__(parent)
        self._mdm = mdm_module
        self.setStyleSheet(f"background: {BRAND['bg']}; color: {BRAND['text']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # Header row
        hdr_row = QHBoxLayout()
        hdr = QLabel("Mobile Device Management")
        hdr.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        self._checkin_btn = QPushButton("🔄  Check-in Now")
        self._checkin_btn.setStyleSheet(BTN)
        self._checkin_btn.clicked.connect(self._do_checkin)
        hdr_row.addWidget(self._checkin_btn)
        layout.addLayout(hdr_row)

        # Status strip
        self._status_lbl = QLabel("Status: Initializing...")
        self._status_lbl.setStyleSheet(f"color: {BRAND['muted']}; font-size: 12px;")
        layout.addWidget(self._status_lbl)

        # Stat cards
        grid = QGridLayout()
        grid.setSpacing(14)
        self._card_hostname     = StatCard("Hostname",     platform.node())
        self._card_os           = StatCard("OS",           platform.system())
        self._card_checkin      = StatCard("Last Check-in", "—")
        self._card_device_id    = StatCard("Device ID",    "—")
        grid.addWidget(self._card_hostname,  0, 0)
        grid.addWidget(self._card_os,        0, 1)
        grid.addWidget(self._card_checkin,   0, 2)
        grid.addWidget(self._card_device_id, 0, 3)
        layout.addLayout(grid)

        # Hardware inventory table
        inv_hdr = QLabel("Hardware Inventory")
        inv_hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        layout.addWidget(inv_hdr)

        self._inv_table = QTableWidget(0, 2)
        self._inv_table.setHorizontalHeaderLabels(["Property", "Value"])
        self._inv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._inv_table.setColumnWidth(0, 180)
        self._inv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._inv_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._inv_table.verticalHeader().setVisible(False)
        self._inv_table.setStyleSheet(TABLE)
        self._inv_table.setAlternatingRowColors(False)
        self._inv_table.setMaximumHeight(280)
        layout.addWidget(self._inv_table)

        layout.addStretch()

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(15000)
        QTimer.singleShot(500, self._refresh)

    def _do_checkin(self):
        self._checkin_btn.setEnabled(False)
        self._status_lbl.setText("Status: Checking in...")
        if self._mdm:
            self._mdm.checkin_now()
        QTimer.singleShot(5000, lambda: self._checkin_btn.setEnabled(True))

    def _refresh(self):
        if not self._mdm:
            return
        if self._mdm.last_checkin:
            self._card_checkin.set_value(self._mdm.last_checkin)
            self._status_lbl.setText(f"Status: ✅ Online")
            self._status_lbl.setStyleSheet(f"color: {BRAND['success']}; font-size: 12px;")
        if self._mdm.device_id:
            self._card_device_id.set_value(str(self._mdm.device_id))

        # Populate inventory
        try:
            hw = self._mdm.hardware_info
            self._inv_table.setRowCount(0)
            skip = {"device_token", "monitors"}
            for k, v in hw.items():
                if k in skip:
                    continue
                row = self._inv_table.rowCount()
                self._inv_table.insertRow(row)
                key_item = QTableWidgetItem(k.replace("_", " ").title())
                key_item.setForeground(QColor(BRAND["muted"]))
                val_item = QTableWidgetItem(str(v))
                val_item.setForeground(QColor(BRAND["text"]))
                self._inv_table.setItem(row, 0, key_item)
                self._inv_table.setItem(row, 1, val_item)
        except Exception:
            pass
