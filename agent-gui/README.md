# NOCKO MDM Agent

Windows-first service agent for NOCKO MDM.

This repository now uses a Zabbix-style delivery model:

- the agent is built on Windows in GitHub Actions
- production serves a customer-specific EXE with embedded bootstrap config instead of rebuilding installers on demand
- the agent runs as a Windows service instead of a scheduled task

## Current Scope

Implemented now:

- service-capable Python agent
- enrollment and check-in against `/api/v1/mdm/windows/*`
- embedded bootstrap config reader for single-file EXE delivery
- PyInstaller build to `dist/NOCKO-Agent.exe`
- Inno Setup installer
- WiX MSI definition

Planned next:

- richer hardware inventory
- remote command execution
- SIEM/event forwarding
- bootstrap config injection from portal/release flow

## Quick Start

```bash
pip install -r requirements.txt
python make_icons.py
python main.py run
```

The agent reads config from:

- Windows: `C:\ProgramData\NOCKO-Agent\config.json`
- dev/non-Windows: `~/.nocko-agent/config.json`

Example config:

```json
{
  "server_url": "https://mdm.it-uae.com",
  "enrollment_token": "YOUR-TOKEN",
  "customer_id": "YOUR-CUSTOMER-ID",
  "checkin_interval": 300,
  "mdm_enabled": true,
  "siem_enabled": false,
  "backup_enabled": false,
  "remote_enabled": false,
  "log_level": "INFO",
  "agent_version": "1.0.0",
  "device_id": ""
}
```

## Service Commands

On Windows, the same executable can run as a service or be managed from the command line:

```powershell
NOCKO-Agent.exe --startup auto install
NOCKO-Agent.exe start
NOCKO-Agent.exe stop
NOCKO-Agent.exe remove
NOCKO-Agent.exe debug
```

When the EXE contains embedded bootstrap config and is launched with no arguments,
it can self-install:

1. writes `C:\ProgramData\NOCKO-Agent\config.json`
2. copies a clean service binary into the install directory
3. installs the Windows service
4. optionally starts the service immediately

## Packaging

### Portable EXE

```powershell
python make_icons.py
pyinstaller agent.spec --noconfirm
```

### Setup EXE

```powershell
ISCC installer\setup.iss
```

### MSI

```powershell
wix build installer\setup.wxs -arch x64 -o release-assets\nocko-agent-x64.msi
```

## Project Structure

```text
agent-gui/
├── main.py
├── config.py
├── logger.py
├── device_info.py
├── service_runtime.py
├── agent.spec
├── config.example.json
├── make_icons.py
├── requirements.txt
├── modules/
│   └── mdm.py
└── installer/
    ├── setup.iss
    └── setup.wxs
```
