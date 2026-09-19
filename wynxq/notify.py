"""Desktop notifications for long local runs.

Uses ``notify-send`` when the distribution provides it. Callers pass a fallback
so the app can fall back to the tray icon; nothing here ever leaves the machine.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

LOG = logging.getLogger(__name__)

APP_ID = "io.github.wynxo.Wynxq"
# Runs shorter than this are not worth interrupting the user for.
MIN_SECONDS = 12.0


def available() -> bool:
    return shutil.which("notify-send") is not None


def send(title: str, body: str = "", urgency: str = "normal") -> bool:
    """Post a notification. Returns True when the desktop accepted it."""
    launcher = shutil.which("notify-send")
    if not launcher:
        return False
    if urgency not in ("low", "normal", "critical"):
        urgency = "normal"
    command = [launcher, "--app-name=Wynxq", f"--urgency={urgency}",
               f"--icon={APP_ID}", str(title)[:120]]
    if body:
        command.append(str(body)[:400])
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=6, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.debug("notify-send failed: %s", exc)
        return False


def should_notify(seconds: float, focused: bool, enabled: bool) -> bool:
    """Only notify for genuinely long work the user has walked away from."""
    return bool(enabled) and not focused and seconds >= MIN_SECONDS


def open_path(path: str) -> bool:
    """Reveal a folder or file in the user's file manager."""
    launcher = shutil.which("xdg-open")
    if not launcher or not path:
        return False
    try:
        subprocess.Popen([launcher, path], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        LOG.debug("xdg-open failed: %s", exc)
        return False


TERMINALS = ("x-terminal-emulator", "konsole", "gnome-terminal", "kgx", "ptyxis",
             "alacritty", "kitty", "wezterm", "foot", "xfce4-terminal", "tilix", "xterm")


def open_terminal(path: str = "") -> bool:
    """Open the user's terminal in ``path``. Never runs a command in it."""
    for name in TERMINALS:
        launcher = shutil.which(name)
        if not launcher:
            continue
        try:
            subprocess.Popen([launcher], cwd=path or None, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False
