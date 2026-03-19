from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from config import (
    AGENT_VERSION,
    UNINSTALL_REGISTRY_KEY,
    WINDOWS_SERVICE_NAME,
    AgentConfig,
    load_config,
    read_embedded_config,
    resolve_agent_version,
    write_executable_without_embedded_config,
)
from logger import configure_logging
from modules.mdm import MdmAgentClient
from service_runtime import run_agent_loop

try:
    import servicemanager  # type: ignore[import-not-found]
    import win32event  # type: ignore[import-not-found]
    import win32service  # type: ignore[import-not-found]
    import win32serviceutil  # type: ignore[import-not-found]
except ImportError:
    servicemanager = None
    win32event = None
    win32service = None
    win32serviceutil = None

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:
    winreg = None


class NockoAgentService(win32serviceutil.ServiceFramework if win32serviceutil else object):
    _svc_name_ = WINDOWS_SERVICE_NAME
    _svc_display_name_ = "NOCKO MDM Agent"
    _svc_description_ = "NOCKO MDM Windows service for enrollment, check-in, and command polling."

    def __init__(self, args):
        if not win32serviceutil or not win32event:
            raise RuntimeError("Windows service support requires pywin32 on Windows")
        super().__init__(args)
        self.stop_event = threading.Event()
        self.h_wait_stop = win32event.CreateEvent(None, 0, 0, None)
        self.config = load_config()
        self.logger = configure_logging(self.config.log_level, self.config.log_dir)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.h_wait_stop)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("NOCKO Agent service starting")
        run_agent_loop(self.config, self.logger, self.stop_event)
        servicemanager.LogInfoMsg("NOCKO Agent service stopped")


def run_console(config_path: str | None = None) -> int:
    config = load_config(config_path)
    logger = configure_logging(config.log_level, config.log_dir)
    stop_event = threading.Event()
    try:
        run_agent_loop(config, logger, stop_event)
    except KeyboardInterrupt:
        logger.info("Stopping agent after keyboard interrupt")
        stop_event.set()
    return 0


def is_windows_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated() -> int:
    """Re-launch ourselves with administrator privileges via UAC."""
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:] or ["bootstrap-install"])
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        None,
        1,  # SW_SHOWNORMAL — shows UAC dialog (0=hidden, may silently fail)
    )
    return 0 if rc > 32 else 1


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


def try_run(args: list[str]) -> bool:
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def prepare_installed_binary(current_exe: Path, target_exe: Path, logger) -> Path:
    if current_exe == target_exe.resolve():
        return target_exe

    # If an older service instance is running, stop it before trying to replace
    # the installed binary in Program Files.
    try_run(["sc", "stop", WINDOWS_SERVICE_NAME])

    try:
        had_embedded = write_executable_without_embedded_config(current_exe, target_exe)
        logger.info(
            "Copied executable to %s%s",
            target_exe,
            " without embedded bootstrap footer" if had_embedded else "",
        )
        return target_exe
    except PermissionError:
        if target_exe.exists():
            logger.warning(
                "Could not overwrite %s because it is in use. Reusing the existing installed binary.",
                target_exe,
            )
            return target_exe
        raise


def register_uninstall_entry(config: AgentConfig, target_exe: Path) -> None:
    if os.name != "nt" or winreg is None:
        return

    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REGISTRY_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, config.agent_display_name)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "NOCKO IT")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, config.agent_version or AGENT_VERSION)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target_exe.parent))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target_exe))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{target_exe}" uninstall')
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, f'"{target_exe}" uninstall --quiet')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def remove_uninstall_entry() -> None:
    if os.name != "nt" or winreg is None:
        return
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REGISTRY_KEY)
    except FileNotFoundError:
        pass


def schedule_cleanup(target_exe: Path, config_path: Path, install_dir: Path, log_dir: Path) -> None:
    """Schedule deletion of agent files after the current process exits."""
    if os.name != "nt":
        return
    import tempfile
    # Write a batch file to a temp location so cmd can delete the exe even
    # while this process is still running.
    bat_lines = [
        "@echo off",
        "ping 127.0.0.1 -n 4 > NUL",          # wait ~3 s for the process to exit
        f'sc stop {WINDOWS_SERVICE_NAME} > NUL 2>&1',
        f'sc delete {WINDOWS_SERVICE_NAME} > NUL 2>&1',
        f'del /f /q "{target_exe}" 2> NUL',
        f'del /f /q "{config_path}" 2> NUL',
        f'rmdir /s /q "{install_dir}" 2> NUL',
        f'rmdir /s /q "{log_dir}" 2> NUL',
        f'del /f /q "%~f0"',                    # self-delete the bat file
    ]
    try:
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="nocko_uninstall_")
        with os.fdopen(fd, "w") as f:
            f.write("\r\n".join(bat_lines))
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass  # cleanup failure is non-fatal


def uninstall_agent(quiet: bool = False) -> int:
    if os.name != "nt":
        return 0
    if not is_windows_admin():
        return relaunch_elevated()

    config = load_config()
    logger = configure_logging(config.log_level, config.log_dir)
    target_exe = Path(sys.executable).resolve()

    try:
        MdmAgentClient(config, logger).decommission("Agent uninstalled")
    except Exception as exc:
        logger.warning("Decommission request failed: %s", exc)

    try_run([str(target_exe), "stop"])
    try_run([str(target_exe), "remove"])
    remove_uninstall_entry()
    schedule_cleanup(target_exe, AgentConfig.config_path(), target_exe.parent, Path(config.log_dir))
    if not quiet:
        logger.info("Uninstall scheduled for %s", target_exe)
    return 0


def is_agent_already_installed(target_exe: Path) -> bool:
    """Return True if a previous installation exists (service OR files)."""
    if target_exe.exists():
        return True
    # Check if Windows service is registered
    result = subprocess.run(
        ["sc", "query", WINDOWS_SERVICE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def cleanup_previous_installation(target_exe: Path, logger) -> None:
    """Stop and remove old service + binary before fresh install."""
    logger.info("Previous installation detected — cleaning up before reinstall")
    try_run([str(target_exe), "stop"])    # stop service gracefully
    try_run([str(target_exe), "remove"])  # unregister service
    # sc delete as fallback
    try_run(["sc", "stop", WINDOWS_SERVICE_NAME])
    try_run(["sc", "delete", WINDOWS_SERVICE_NAME])
    # Delete old binary (may be locked — ignore)
    try:
        if target_exe.exists():
            target_exe.unlink()
    except PermissionError:
        logger.warning("Could not delete locked EXE — will be overwritten on next boot")
    remove_uninstall_entry()


def bootstrap_install_from_embedded_config() -> int:
    embedded = read_embedded_config(sys.executable)
    if not embedded:
        return -1

    if os.name != "nt":
        config = AgentConfig(**{**AgentConfig().__dict__, **embedded})
        config.save()
        logger = configure_logging(config.log_level, config.log_dir)
        logger.info("Embedded config written. Running in console mode on non-Windows host.")
        stop_event = threading.Event()
        run_agent_loop(config, logger, stop_event)
        return 0

    if not is_windows_admin():
        return relaunch_elevated()

    config = AgentConfig(**{**AgentConfig().__dict__, **embedded})
    config.save()
    logger = configure_logging(config.log_level, config.log_dir)

    target_dir = Path(config.install_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_exe = target_dir / "NOCKO-Agent.exe"
    current_exe = Path(sys.executable).resolve()

    # ── Reinstall: remove old version first ───────────────────────────────────
    if current_exe != target_exe.resolve() and is_agent_already_installed(target_exe):
        cleanup_previous_installation(target_exe, logger)

    runtime_exe = prepare_installed_binary(current_exe, target_exe, logger)

    run_command([str(runtime_exe), "--startup", "auto", "install"])
    if config.start_immediately:
        run_command([str(runtime_exe), "start"])
    register_uninstall_entry(config, runtime_exe)
    logger.info("Bootstrap install complete")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("--config", dest="config_path")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    service_commands = {"install", "update", "remove", "start", "stop", "restart", "debug"}
    if win32serviceutil and any(arg in service_commands for arg in sys.argv[1:]):
        win32serviceutil.HandleCommandLine(NockoAgentService)
        return 0

    args = parse_args()
    if args.version:
        print(resolve_agent_version())
        return 0

    if args.command == "uninstall":
        return uninstall_agent(args.quiet)

    if args.command in {"bootstrap-install", "bootstrap"}:
        return bootstrap_install_from_embedded_config()

    if len(sys.argv) == 1:
        bootstrap_result = bootstrap_install_from_embedded_config()
        if bootstrap_result >= 0:
            return bootstrap_result

        if win32serviceutil:
            try:
                servicemanager.Initialize()
                servicemanager.PrepareToHostSingle(NockoAgentService)
                servicemanager.StartServiceCtrlDispatcher()
                return 0
            except Exception:
                pass

    if args.command in {"run", "console"}:
        return run_console(args.config_path)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
