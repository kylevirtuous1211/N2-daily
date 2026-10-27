"""Desktop launcher: start the N2 Daily server if needed, then open it in an app window."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("N2_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/"
IDLE_TIMEOUT_SECONDS = 15 * 60
BROWSER_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
]


def server_status() -> str:
    """'ours', 'other' (port taken by something else) or 'down'."""
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1) as response:
            return "ours" if json.load(response).get("app") == "n2-daily" else "other"
    except (OSError, ValueError):
        return "down"


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "N2 Daily", 0x10)


def start_server() -> None:
    log_path = Path(os.environ.get("LOCALAPPDATA", APP_DIR)) / "N2Daily" / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with open(log_path, "a", encoding="utf-8") as log:
        subprocess.Popen(
            [str(interpreter), str(APP_DIR / "serve.py"), "--port", str(PORT), "--idle-timeout", str(IDLE_TIMEOUT_SECONDS)],
            cwd=APP_DIR, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True,
        )


def open_window() -> None:
    browser = next((path for path in BROWSER_CANDIDATES if path.is_file()), None)
    browser = browser or (Path(found) if (found := shutil.which("chrome") or shutil.which("msedge")) else None)
    if browser is None:
        webbrowser.open(URL)
        return
    subprocess.Popen([str(browser), f"--app={URL}", "--window-size=1180,920"], close_fds=True)


def main() -> None:
    status = server_status()
    if status == "other":
        show_error(f"Port {PORT} is used by another program. Close it, or set N2_PORT to a free port.")
        return
    if status == "down":
        start_server()
        deadline = time.monotonic() + 15
        while server_status() != "ours":
            if time.monotonic() > deadline:
                show_error("The N2 Daily server did not start. See %LOCALAPPDATA%\\N2Daily\\server.log for details.")
                return
            time.sleep(0.2)
    open_window()


if __name__ == "__main__":
    main()
