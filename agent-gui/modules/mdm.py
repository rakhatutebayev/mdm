"""
NOCKO Agent — MDM Module
Python port of nocko-mdm-agent.ps1 with cross-platform inventory
and command execution. Windows-specific calls are guarded with
platform checks so the module imports cleanly on macOS/Linux for dev.
"""
import platform
import subprocess
import threading
import time
from typing import Optional

import requests

from config import config
from logger import get_logger

log = get_logger("mdm")

IS_WINDOWS = platform.system() == "Windows"


# ── Hardware Inventory ──────────────────────────────────────────────────────

def _get_hardware_info() -> dict:
    import socket
    info: dict = {
        "device_token":   config.enrollment_token,
        "hostname":       socket.gethostname(),
        "os_version":     platform.version(),
        "platform":       platform.system(),
        "agent_version":  config.agent_version,
    }

    if IS_WINDOWS:
        try:
            import wmi  # type: ignore
            c = wmi.WMI()

            bios = c.Win32_BIOS()[0]
            cs   = c.Win32_ComputerSystem()[0]
            os_  = c.Win32_OperatingSystem()[0]
            cpu  = c.Win32_Processor()[0]

            info.update({
                "serial_number": bios.SerialNumber.strip(),
                "model":         f"{cs.Manufacturer} {cs.Model}".strip(),
                "manufacturer":  cs.Manufacturer,
                "ram_gb":        round(int(cs.TotalPhysicalMemory) / 1_073_741_824, 1),
                "cpu_model":     cpu.Name.strip(),
                "os_version":    f"{os_.Caption} Build {os_.BuildNumber}",
            })

            # Disk C:
            for disk in c.Win32_LogicalDisk(DeviceID="C:"):
                info["disk_gb"] = round(int(disk.Size) / 1_073_741_824, 0)

            # Network
            adapters = [a for a in c.Win32_NetworkAdapterConfiguration() if a.IPEnabled]
            if adapters:
                a = adapters[0]
                info["ip_address"]  = (a.IPAddress or [""])[0]
                info["mac_address"] = a.MACAddress or ""

            # Entra / Domain join
            try:
                dsreg = subprocess.check_output(["dsregcmd", "/status"],
                                                text=True, timeout=10,
                                                stderr=subprocess.DEVNULL)
                info["entra_joined"]  = "AzureAdJoined : YES" in dsreg
                info["domain_joined"] = "DomainJoined : YES" in dsreg
            except Exception:
                info["entra_joined"]  = False
                info["domain_joined"] = False

        except Exception as e:
            log.warning(f"WMI inventory partial: {e}")

    else:
        # macOS / Linux dev fallback
        import psutil
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        info.update({
            "serial_number": "DEV-SERIAL",
            "model":         platform.node(),
            "manufacturer":  "Dev Machine",
            "ram_gb":        round(vm.total / 1_073_741_824, 1),
            "disk_gb":       round(disk.total / 1_073_741_824, 0),
            "cpu_model":     platform.processor() or "Unknown CPU",
            "ip_address":    "127.0.0.1",
            "mac_address":   "00:00:00:00:00:00",
            "entra_joined":  False,
            "domain_joined": False,
        })

    return info


# ── Command Handlers ────────────────────────────────────────────────────────

def _exec_lock():
    if IS_WINDOWS:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    else:
        log.info("[STUB] Lock workstation")


def _exec_shutdown():
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/s", "/f", "/t", "0"])
    else:
        log.info("[STUB] Shutdown")


def _exec_restart():
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/r", "/f", "/t", "0"])
    else:
        log.info("[STUB] Restart")


def _exec_message(payload: dict) -> str:
    title = payload.get("title", "NOCKO MDM")
    msg   = payload.get("message", "Message from IT Administrator")
    if IS_WINDOWS:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app:
            mb = QMessageBox()
            mb.setWindowTitle(title)
            mb.setText(msg)
            mb.exec()
    else:
        log.info(f"[MSG] {title}: {msg}")
    return "Message displayed"


def _exec_run_script(payload: dict) -> str:
    script = payload.get("script", "")
    if IS_WINDOWS:
        result = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout + result.stderr
    else:
        result = subprocess.run(["bash", "-c", script],
                                capture_output=True, text=True, timeout=120)
        return result.stdout + result.stderr


def _exec_install_app(payload: dict) -> str:
    if not IS_WINDOWS:
        return f"[STUB] Install: {payload}"
    if payload.get("winget_id"):
        result = subprocess.run(
            ["winget", "install", "--id", payload["winget_id"],
             "--silent", "--accept-source-agreements", "--accept-package-agreements"],
            capture_output=True, text=True
        )
        return result.stdout + result.stderr
    elif payload.get("msi_url"):
        import tempfile, urllib.request
        tmp = tempfile.mktemp(suffix=".msi")
        urllib.request.urlretrieve(payload["msi_url"], tmp)
        subprocess.run(["msiexec.exe", "/i", tmp, "/quiet", "/norestart"], timeout=300)
        return f"MSI installed from {payload['msi_url']}"
    raise ValueError("No valid install source (winget_id / msi_url required)")


def _exec_uninstall_app(payload: dict) -> str:
    if not IS_WINDOWS:
        return f"[STUB] Uninstall: {payload}"
    if payload.get("winget_id"):
        result = subprocess.run(
            ["winget", "uninstall", "--id", payload["winget_id"], "--silent"],
            capture_output=True, text=True
        )
        return result.stdout + result.stderr
    raise ValueError("winget_id required for uninstall")


def _exec_set_wallpaper(payload: dict) -> str:
    if not IS_WINDOWS:
        return f"[STUB] Set wallpaper: {payload.get('url')}"
    import urllib.request, ctypes, tempfile
    tmp = tempfile.mktemp(suffix=".jpg")
    urllib.request.urlretrieve(payload["url"], tmp)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, tmp, 3)
    return f"Wallpaper set from {payload['url']}"


def _execute_command(cmd: dict):
    cmd_type = cmd.get("command_type", "")
    payload  = cmd.get("payload") or {}
    output   = ""
    status   = "success"

    log.info(f"Executing command: {cmd_type}")
    try:
        if cmd_type in ("LOCK", "LOCK_DEVICE"):
            _exec_lock()
        elif cmd_type == "SHUTDOWN":
            _exec_shutdown()
        elif cmd_type in ("REBOOT", "RESTART"):
            _exec_restart()
        elif cmd_type == "MESSAGE":
            output = _exec_message(payload)
        elif cmd_type == "RUN_SCRIPT":
            output = _exec_run_script(payload)
        elif cmd_type in ("INSTALL_APP", "ANDROID_INSTALL_APP"):
            output = _exec_install_app(payload)
        elif cmd_type == "UNINSTALL_APP":
            output = _exec_uninstall_app(payload)
        elif cmd_type == "SET_WALLPAPER":
            output = _exec_set_wallpaper(payload)
        elif cmd_type == "COLLECT_INVENTORY":
            output = "Inventory sent on check-in"
        else:
            output = f"Unknown command: {cmd_type}"
            status = "failed"
    except Exception as e:
        output = str(e)
        status = "failed"
        log.error(f"Command {cmd_type} failed: {e}")

    # ACK
    try:
        requests.post(
            f"{config.mdm_server}/mdm/windows/commands/{cmd['id']}/ack",
            json={"status": status, "output": output},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Failed to ACK command {cmd.get('id')}: {e}")


# ── Check-in Loop ───────────────────────────────────────────────────────────

class MDMModule:
    """Runs MDM check-in on a background thread."""

    def __init__(self, on_status_change=None):
        self._thread: Optional[threading.Thread] = None
        self._stop   = threading.Event()
        self.on_status_change = on_status_change  # callback(status: str)
        self.last_checkin: Optional[str] = None
        self.device_id: Optional[str]   = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mdm-loop")
        self._thread.start()
        log.info("MDM module started")

    def stop(self):
        self._stop.set()
        log.info("MDM module stopped")

    def checkin_now(self):
        threading.Thread(target=self._do_checkin, daemon=True).start()

    def _loop(self):
        while not self._stop.is_set():
            self._do_checkin()
            self._stop.wait(timeout=config.checkin_interval * 60)

    def _do_checkin(self):
        if not config.enrollment_token:
            log.warning("MDM: enrollment token not set, skipping check-in")
            self._notify("Not enrolled")
            return

        log.info("MDM check-in starting...")
        try:
            hw   = _get_hardware_info()
            resp = requests.post(
                f"{config.mdm_server}/mdm/windows/checkin",
                json=hw,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.device_id    = data.get("device_id")
            self.last_checkin = time.strftime("%H:%M:%S")
            log.info(f"Check-in OK — Device: {self.device_id} | Commands: {len(data.get('commands', []))}")
            self._notify("Online")

            for cmd in data.get("commands", []):
                _execute_command(cmd)

        except Exception as e:
            log.warning(f"Check-in failed: {e}")
            self._notify("Offline")

    def _notify(self, status: str):
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception:
                pass

    @property
    def hardware_info(self) -> dict:
        return _get_hardware_info()
