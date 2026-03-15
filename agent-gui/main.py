from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path

from config import (
    AGENT_VERSION,
    WINDOWS_SERVICE_NAME,
    AgentConfig,
    load_config,
    read_embedded_config,
    write_executable_without_embedded_config,
)
from logger import configure_logging
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
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:] or ["bootstrap-install"])
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        None,
        1,
    )
    return 0 if rc > 32 else 1


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


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

    if current_exe != target_exe.resolve():
        had_embedded = write_executable_without_embedded_config(current_exe, target_exe)
        logger.info(
            "Copied executable to %s%s",
            target_exe,
            " without embedded bootstrap footer" if had_embedded else "",
        )

    run_command([str(target_exe), "--startup", "auto", "install"])
    if config.start_immediately:
        run_command([str(target_exe), "start"])
    logger.info("Bootstrap install complete")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("--config", dest="config_path")
    parser.add_argument("--version", action="store_true")
    return parser.parse_args()


def main() -> int:
    service_commands = {"install", "update", "remove", "start", "stop", "restart", "debug"}
    if win32serviceutil and any(arg in service_commands for arg in sys.argv[1:]):
        win32serviceutil.HandleCommandLine(NockoAgentService)
        return 0

    args = parse_args()
    if args.version:
        print(AGENT_VERSION)
        return 0

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
