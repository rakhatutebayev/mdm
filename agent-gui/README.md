# NOCKO Unified Agent GUI

A modular, extensible Windows GUI agent built with Python + PyQt6.

## Architecture

```
agent-gui/
├── main.py              # Entry point — tray app
├── config.py            # JSON config (ProgramData/NOCKO-Agent/)
├── logger.py            # Rotating file logger + UI callbacks
├── modules/
│   ├── mdm.py           # ✅ MDM — check-in, inventory, commands
│   ├── siem.py          # ✅ SIEM — Windows Event Log collection
│   ├── backup.py        # 🔜 Backup (stub, v2)
│   └── remote.py        # 🔜 Remote Access (stub, v2)
├── ui/
│   ├── tray.py          # System tray icon + context menu
│   ├── main_window.py   # Dashboard with sidebar nav
│   └── pages/
│       ├── overview.py      # Module status cards
│       ├── mdm_page.py      # Hardware inventory + check-in
│       ├── siem_page.py     # Color-coded event table
│       ├── backup_page.py   # Coming soon UI
│       ├── remote_page.py   # Coming soon UI
│       └── settings_page.py # MDM server, token, intervals
├── make_icons.py        # Generate PNG icons (run once)
├── agent.spec           # PyInstaller build config
└── installer/
    └── setup.iss        # Inno Setup installer script
```

## Development Setup (macOS/Linux)

```bash
cd agent-gui
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Generate icons first
python make_icons.py

# Run the app
python main.py
```

## Windows Build (on Windows machine)

```powershell
cd agent-gui
pip install -r requirements.txt
pip install pyinstaller pywin32 wmi

# Generate icons
python make_icons.py

# Build exe
pyinstaller agent.spec

# Create installer (requires Inno Setup)
ISCC installer\setup.iss
```

## Module Roadmap

| Module        | v1 Status | Description |
|---------------|-----------|-------------|
| MDM           | ✅ Done   | Device check-in, inventory, remote commands |
| SIEM          | ✅ Done   | Windows event log collection + forwarding |
| Backup        | 🔜 v2     | File sync to NOCKO servers |
| Remote Access | 🔜 v2     | AnyDesk-style over WebSocket |

## Config File Location

- **Windows:** `C:\ProgramData\NOCKO-Agent\config.json`
- **macOS/Linux:** `~/.nocko-agent/config.json`
