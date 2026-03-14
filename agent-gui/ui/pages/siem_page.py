"""NOCKO Agent — SIEM Page"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QColor

BRAND = {
    "bg": "#0f0f1a", "card": "#1a1a2e", "accent": "#2563eb",
    "accent_hover": "#1d4ed8", "text": "#e2e8f0", "muted": "#94a3b8",
    "border": "#1e293b", "success": "#10b981", "warning": "#f59e0b",
    "danger": "#ef4444",
}

TABLE_STYLE = f"""
QTableWidget {{
    background: {BRAND['card']}; color: {BRAND['text']};
    gridline-color: {BRAND['border']}; border: 1px solid {BRAND['border']};
    border-radius: 10px; font-size: 12px;
}}
QHeaderView::section {{
    background: {BRAND['card']}; color: {BRAND['muted']};
    border: none; border-bottom: 1px solid {BRAND['border']};
    padding: 8px; font-size: 11px;
}}
QTableWidget::item:selected {{ background: rgba(37,99,235,0.2); }}
"""

EVENT_LEVEL_COLORS = {
    "security": "#f59e0b",
    "system":   "#60a5fa",
    "app":      "#94a3b8",
}

SEVERITY_COLORS = {
    4624: "#10b981",  # Logon OK
    4625: "#ef4444",  # Logon fail
    4720: "#f59e0b",  # Account created
    4726: "#ef4444",  # Account deleted
    4740: "#ef4444",  # Lockout
}


class SIEMPage(QWidget):
    def __init__(self, siem_module=None, parent=None):
        super().__init__(parent)
        self._siem = siem_module
        self.setStyleSheet(f"background: {BRAND['bg']}; color: {BRAND['text']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # Header
        hdr_row = QHBoxLayout()
        hdr = QLabel("Security Information & Event Management")
        hdr.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        refresh_btn = QPushButton("🔄  Collect Now")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{ background: {BRAND['accent']}; color: white;
              border: none; padding: 9px 18px; border-radius: 8px; font-size: 12px; font-weight: 600; }}
            QPushButton:hover {{ background: {BRAND['accent_hover']}; }}
        """)
        refresh_btn.clicked.connect(self._collect_now)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        # Stats row
        stats_row = QHBoxLayout()
        self._total_lbl  = QLabel("Events collected: 0")
        self._sent_lbl   = QLabel("Events sent: 0")
        self._status_lbl = QLabel("Status: Starting...")
        for lbl in (self._total_lbl, self._sent_lbl, self._status_lbl):
            lbl.setStyleSheet(f"color: {BRAND['muted']}; font-size: 12px;")
            stats_row.addWidget(lbl)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # Events table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Time", "Log", "Event ID", "Event Name", "Message"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed);    self._table.setColumnWidth(0, 140)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed);    self._table.setColumnWidth(1, 80)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed);    self._table.setColumnWidth(2, 80)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed);    self._table.setColumnWidth(3, 180)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(TABLE_STYLE)
        self._table.setShowGrid(True)
        layout.addWidget(self._table)

        # Timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(10000)
        QTimer.singleShot(1000, self._refresh)

    def _collect_now(self):
        if self._siem:
            self._siem.collect_now()
        QTimer.singleShot(3000, self._refresh)

    def _refresh(self):
        if not self._siem:
            return
        events = self._siem.recent_events
        self._total_lbl.setText(f"Events buffered: {len(events)}")
        self._sent_lbl.setText(f"Events sent: {self._siem.events_sent}")

        self._table.setRowCount(0)
        for ev in reversed(events[-200:]):
            row = self._table.rowCount()
            self._table.insertRow(row)
            eid = ev.get("event_id", 0)
            color = QColor(SEVERITY_COLORS.get(eid, BRAND["text"]))
            log_color = QColor(EVENT_LEVEL_COLORS.get(ev.get("log", "").lower(), BRAND["muted"]))

            items = [
                QTableWidgetItem(str(ev.get("time", ""))),
                QTableWidgetItem(str(ev.get("log", ""))),
                QTableWidgetItem(str(eid)),
                QTableWidgetItem(str(ev.get("event_name", ""))),
                QTableWidgetItem(str(ev.get("message", ""))[:120]),
            ]
            for col, item in enumerate(items):
                fg = log_color if col == 1 else color if col in (2, 3) else QColor(BRAND["text"])
                item.setForeground(fg)
                self._table.setItem(row, col, item)

        if events:
            self._status_lbl.setText("Status: ✅ Collecting")
            self._status_lbl.setStyleSheet(f"color: {BRAND['success']}; font-size: 12px;")
