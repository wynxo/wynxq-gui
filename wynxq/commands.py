"""Bounded local command execution, independent of screen-control permission."""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import subprocess
import time


OUTPUT_LIMIT = 32000


def run_command(command: str, cwd: str = "", timeout: int = 60, cancel=None) -> dict:
    """Run Bash with captured output; Stop/timeout terminates its process group.

    Commands run as the current user, without an interactive stdin or elevated
    privileges. The engine applies the same approval policy as other actions.
    """
    directory = Path(cwd).expanduser() if cwd else Path.home()
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("The working directory is not a folder")
    if not command.strip() or "\0" in command:
        raise ValueError("Enter a non-empty command without NUL characters")
    if cancel is not None and cancel.is_set():
        return {"ok": False, "error": "Stopped before execution"}
    process = subprocess.Popen(
        ["/bin/bash", "-c", command], cwd=directory,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    truncated = False
    error = ""
    started = time.monotonic()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if cancel is not None and cancel.is_set():
                    error = "Stopped; the command may have made partial changes"
                    break
                if time.monotonic() - started >= timeout:
                    error = f"Command timed out after {timeout} seconds"
                    break
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = OUTPUT_LIMIT - len(output)
                    output.extend(chunk[:room])
                    truncated = truncated or len(chunk) > room
            # A command can close stdout before finishing.
            while not error and process.poll() is None:
                if cancel is not None and cancel.is_set():
                    error = "Stopped; the command may have made partial changes"
                elif time.monotonic() - started >= timeout:
                    error = f"Command timed out after {timeout} seconds"
                else:
                    time.sleep(0.05)
    finally:
        # Kill descendants too, including those retaining the output pipe after
        # the shell exits. GUI applications use open_app instead of this tool.
        if error or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
    result = {"ok": not error and process.returncode == 0,
              "exit_code": process.returncode, "output": output.decode("utf-8", "replace"),
              "cwd": str(directory), "command": command, "truncated": truncated}
    if error:
        result["error"] = error
    elif process.returncode:
        result["error"] = f"Command exited with status {process.returncode}"
    return result
