"""Start and track the NIFTY 100 scan as a single local process.

Telegram ``/scan`` and the nightly Task Scheduler entry both go through this
module so two scans cannot run at once. The lock file stores the child PID;
stale locks are cleared when that PID is no longer alive.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

LOG = logging.getLogger("telegram.scan_control")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = PROJECT_ROOT / ".scan_lock.json"
SCAN_SCRIPT = PROJECT_ROOT / "crone-job" / "run_nifty100.py"
SCAN_WORKER = Path(__file__).resolve().parent / "scan_worker.py"
LOG_DIRECTORY = PROJECT_ROOT / "telegram" / "logs"


@dataclass(frozen=True)
class ScanStatus:
    running: bool
    pid: int | None = None
    started_at: str | None = None
    trigger: str | None = None
    limit: int | None = None
    command: list[str] | None = None
    log_file: str | None = None


@dataclass(frozen=True)
class StartResult:
    started: bool
    message: str
    status: ScanStatus


def get_status() -> ScanStatus:
    """Return whether a scan child process is alive right now."""

    payload = _read_lock()
    if not payload:
        return ScanStatus(running=False)

    pid = payload.get("pid")
    if not isinstance(pid, int) or not _pid_is_running(pid):
        _clear_lock()
        return ScanStatus(running=False)

    return ScanStatus(
        running=True,
        pid=pid,
        started_at=str(payload.get("started_at") or ""),
        trigger=str(payload.get("trigger") or ""),
        limit=payload.get("limit"),
        command=list(payload.get("command") or []),
        log_file=str(payload.get("log_file") or ""),
    )


def try_start_scan(
    *,
    trigger: str,
    limit: int | None = None,
    python_executable: str | None = None,
) -> StartResult:
    """Start ``run_nifty100.py`` if idle. Otherwise explain that a scan is busy."""

    current = get_status()
    if current.running:
        return StartResult(
            started=False,
            message=_busy_message(current),
            status=current,
        )

    if not SCAN_SCRIPT.is_file():
        return StartResult(
            started=False,
            message=f"Scan script not found: {SCAN_SCRIPT}",
            status=ScanStatus(running=False),
        )
    if not SCAN_WORKER.is_file():
        return StartResult(
            started=False,
            message=f"Scan worker not found: {SCAN_WORKER}",
            status=ScanStatus(running=False),
        )

    if limit is not None and limit < 1:
        return StartResult(
            started=False,
            message="Limit must be a positive integer (example: /scan 3).",
            status=ScanStatus(running=False),
        )

    executable = python_executable or sys.executable
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIRECTORY / f"scan_{stamp}_{trigger}.log"
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    # The worker opens the log itself so nightly Task Scheduler can exit while
    # the scan keeps running.
    command = [
        executable,
        str(SCAN_WORKER),
        "--log-file",
        str(log_file),
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as error:
        return StartResult(
            started=False,
            message=f"Could not start the scan process: {error}",
            status=ScanStatus(running=False),
        )

    # DETACHED_PROCESS on Windows makes Popen.poll() unreliable, so check the PID
    # through the OS after a short settle time instead.
    time.sleep(0.8)
    if not _pid_is_running(process.pid):
        return StartResult(
            started=False,
            message=(
                "Scan process exited immediately after start. "
                f"Check the log: {log_file}"
            ),
            status=ScanStatus(running=False),
        )

    payload = {
        "pid": process.pid,
        "started_at": started_at,
        "trigger": trigger,
        "limit": limit,
        "command": command,
        "log_file": str(log_file),
    }
    _write_lock(payload)

    scope = f"first {limit} symbol(s)" if limit is not None else "full NIFTY 100"
    message = (
        f"Scan started ({scope}).\n"
        f"Trigger: {trigger}\n"
        f"PID: {process.pid}\n"
        "I will pause Telegram command listening until this scan finishes "
        "so app-code replies can reach the scanner."
    )
    LOG.info("Started scan pid=%s trigger=%s limit=%s", process.pid, trigger, limit)
    return StartResult(started=True, message=message, status=get_status())


def wait_until_scan_finishes(poll_seconds: float = 5.0) -> ScanStatus:
    """Block until the locked scan process exits (used by the Telegram bot)."""

    while True:
        status = get_status()
        if not status.running:
            return status
        time.sleep(poll_seconds)


def format_status(status: ScanStatus | None = None) -> str:
    status = status or get_status()
    if not status.running:
        return "No scan is running right now. Send /scan to start one."

    lines = [
        "Scan is running.",
        f"PID: {status.pid}",
        f"Started: {status.started_at or '?'}",
        f"Trigger: {status.trigger or '?'}",
    ]
    if status.limit is not None:
        lines.append(f"Limit: {status.limit}")
    else:
        lines.append("Limit: full NIFTY 100")
    if status.log_file:
        lines.append(f"Log: {status.log_file}")
    return "\n".join(lines)


def _busy_message(status: ScanStatus) -> str:
    return (
        "A scan is already running.\n"
        f"{format_status(status)}\n"
        "Wait for it to finish before starting another."
    )


def _read_lock() -> dict[str, Any] | None:
    if not LOCK_FILE.is_file():
        return None
    try:
        payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_lock(payload: dict[str, Any]) -> None:
    tmp = LOCK_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(LOCK_FILE)


def _clear_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        LOG.exception("Could not remove stale scan lock file.")


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_pid_is_running(pid: int) -> bool:
    # Avoid shelling out: OpenProcess is enough to know the PID still exists.
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        if not ok:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
