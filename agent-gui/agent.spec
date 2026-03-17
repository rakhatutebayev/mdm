# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
root = Path.cwd()
icon_path = root / "assets" / "favicon.ico"

a = Analysis(
    ["main.py"],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "win32timezone",
        "servicemanager",
        "win32service",
        "win32serviceutil",
        "win32event",
        "pywintypes",
        "paho.mqtt.client",
        "paho.mqtt.properties",
        "paho.mqtt.packettypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude large libraries not used by the agent
    excludes=[
        "tkinter", "_tkinter",
        "matplotlib", "numpy", "scipy", "pandas",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "PIL",
        "PIL._tkinter_finder",
        "test", "unittest", "doctest", "pdb", "pydoc",
        "xmlrpc", "ftplib", "imaplib", "poplib", "smtplib",
        "http.server", "cgi", "cgitb",
        "sqlite3",
        "curses",
        "lib2to3",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NOCKO-Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX not available on GitHub runner — skip to save build time
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)
