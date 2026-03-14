"""
Generate NOCKO Agent icons programmatically using PyQt6.
Run: python make_icons.py
Creates:  ui/assets/nocko.png, nocko_online.png, nocko_offline.png
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QColor, QFont, QPixmap, QBrush, QRadialGradient
from PyQt6.QtCore import Qt, QRect

app = QApplication.instance() or QApplication(sys.argv)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "ui", "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)


def make_icon(filename: str, bg_color: str, dot_color: str, size: int = 256):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background circle
    p.setBrush(QBrush(QColor(bg_color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)

    # "N" letter
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", int(size * 0.42), QFont.Weight.Black)
    p.setFont(font)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "N")

    # Status dot (bottom-right)
    dot_r = int(size * 0.18)
    dot_x = size - dot_r - int(size * 0.08)
    dot_y = size - dot_r - int(size * 0.08)
    p.setBrush(QBrush(QColor(dot_color)))
    p.setPen(QColor("#0f0f1a"))
    p.drawEllipse(dot_x, dot_y, dot_r, dot_r)

    p.end()
    path = os.path.join(ASSETS_DIR, filename)
    pix.save(path, "PNG")
    print(f"Saved: {path}")


# Main icon (default / neutral)
make_icon("nocko.png",         bg_color="#2563eb", dot_color="#94a3b8")
# Online (green dot)
make_icon("nocko_online.png",  bg_color="#2563eb", dot_color="#10b981")
# Offline (red dot)
make_icon("nocko_offline.png", bg_color="#1e293b", dot_color="#ef4444")

print("All icons generated ✅")
