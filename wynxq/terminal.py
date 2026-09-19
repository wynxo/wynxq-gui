"""A real shell session behind the Terminal panel.

Not `subprocess.run` per command: a PTY-backed interactive shell, so `cd`
persists, prompts appear, `top` redraws, and Ctrl+C reaches the foreground
process group the way it does in any other terminal. Output is read on the Qt
event loop through a socket notifier, so nothing blocks the GUI thread.

ANSI is parsed into styled spans rather than stripped, because a build log that
loses its red is a build log you have to re-read.
"""
from __future__ import annotations

import fcntl
import os
import re
import signal
import struct
import termios
from pathlib import Path

# Keep the scrollback bounded: a `yes` typo should not exhaust memory.
MAX_LINES = 4000
MAX_LINE_LENGTH = 4000

CSI = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")
OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
OTHER_ESCAPE = re.compile(r"\x1b[()#][0-9A-Za-z]|\x1b[=>NOM78]|\x1b\][^\x07]*\x07")

# The 16 ANSI slots, named so the QML side maps them onto Theme tokens rather
# than inventing sixteen more colours.
ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


class Style:
    """The subset of SGR that a build log actually uses."""

    __slots__ = ("fg", "bold", "dim", "italic", "underline", "inverse")

    def __init__(self):
        self.fg = ""
        self.bold = False
        self.dim = False
        self.italic = False
        self.underline = False
        self.inverse = False

    def copy(self) -> "Style":
        clone = Style()
        clone.fg, clone.bold, clone.dim = self.fg, self.bold, self.dim
        clone.italic, clone.underline, clone.inverse = self.italic, self.underline, self.inverse
        return clone

    def reset(self) -> None:
        self.__init__()

    def as_dict(self) -> dict:
        return {"fg": self.fg, "bold": self.bold, "dim": self.dim,
                "italic": self.italic, "underline": self.underline,
                "inverse": self.inverse}

    def key(self) -> tuple:
        return (self.fg, self.bold, self.dim, self.italic, self.underline, self.inverse)


def _apply_sgr(style: Style, parameters: str) -> None:
    codes = [int(part) for part in parameters.split(";") if part.isdigit()] or [0]
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            style.reset()
        elif code == 1:
            style.bold = True
        elif code == 2:
            style.dim = True
        elif code == 3:
            style.italic = True
        elif code == 4:
            style.underline = True
        elif code == 7:
            style.inverse = True
        elif code in (21, 22):
            style.bold = style.dim = False
        elif code == 23:
            style.italic = False
        elif code == 24:
            style.underline = False
        elif code == 27:
            style.inverse = False
        elif 30 <= code <= 37:
            style.fg = ANSI_NAMES[code - 30]
        elif 90 <= code <= 97:
            style.fg = "bright" + ANSI_NAMES[code - 90].capitalize()
        elif code == 39:
            style.fg = ""
        elif code == 38 and index + 1 < len(codes):
            # 256-colour and truecolour collapse onto the nearest named slot;
            # the panel is a log, not a framebuffer.
            if codes[index + 1] == 5 and index + 2 < len(codes):
                style.fg = _from_256(codes[index + 2])
                index += 2
            elif codes[index + 1] == 2 and index + 4 < len(codes):
                style.fg = _from_rgb(codes[index + 2], codes[index + 3], codes[index + 4])
                index += 4
        index += 1


def _from_256(value: int) -> str:
    if value < 8:
        return ANSI_NAMES[value]
    if value < 16:
        return "bright" + ANSI_NAMES[value - 8].capitalize()
    if value >= 232:
        return "white" if value >= 244 else ""
    value -= 16
    red, green, blue = value // 36, (value % 36) // 6, value % 6
    return _from_rgb(red * 51, green * 51, blue * 51)


def _from_rgb(red: int, green: int, blue: int) -> str:
    peak = max(red, green, blue)
    if peak < 60:
        return ""
    bright = peak > 170
    high = [channel > peak * 0.65 for channel in (red, green, blue)]
    name = {(True, False, False): "red", (False, True, False): "green",
            (False, False, True): "blue", (True, True, False): "yellow",
            (True, False, True): "magenta", (False, True, True): "cyan",
            (True, True, True): "white"}.get(tuple(high), "white")
    return ("bright" + name.capitalize()) if bright else name


class AnsiScreen:
    """A scrollback of styled lines, updated by feeding it PTY output.

    Only the cursor movement a line-oriented program needs is honoured:
    carriage return, backspace, erase-in-line and erase-in-display. A
    full-screen program still runs — it simply renders as the sequence of
    frames it emits rather than being composited onto a grid.
    """

    def __init__(self, max_lines: int = MAX_LINES):
        self.max_lines = max_lines
        self.lines: list[list[dict]] = [[]]
        self.column = 0
        self.style = Style()
        self.revision = 0
        self._dropped = 0

    # ---------------------------------------------------------------- write
    def _current(self) -> list[dict]:
        return self.lines[-1]

    def _plain(self, line: list[dict]) -> str:
        return "".join(span["text"] for span in line)

    def _set_plain(self, line: list[dict], text: str, style: Style) -> None:
        del line[:]
        if text:
            line.append({"text": text, **style.as_dict()})

    def _put(self, text: str) -> None:
        if not text:
            return
        line = self._current()
        plain = self._plain(line)
        if self.column >= len(plain):
            # Appending: extend the last span when the style is unchanged.
            padding = " " * (self.column - len(plain))
            if line and line[-1].get("_key") == self.style.key():
                line[-1]["text"] += padding + text
            else:
                span = {"text": padding + text, **self.style.as_dict()}
                span["_key"] = self.style.key()
                line.append(span)
            self.column = len(plain) + len(padding) + len(text)
        else:
            # Overwriting (a progress bar redrawing itself): rebuild the line.
            merged = plain[:self.column] + text + plain[self.column + len(text):]
            self._set_plain(line, merged[:MAX_LINE_LENGTH], self.style)
            self.column = min(self.column + len(text), MAX_LINE_LENGTH)
        if len(self._plain(line)) > MAX_LINE_LENGTH:
            self._set_plain(line, self._plain(line)[:MAX_LINE_LENGTH], self.style)

    def _newline(self) -> None:
        self.lines.append([])
        self.column = 0
        while len(self.lines) > self.max_lines:
            self.lines.pop(0)
            self._dropped += 1

    def feed(self, data: str) -> None:
        data = OSC.sub("", data)
        data = OTHER_ESCAPE.sub("", data)
        index = 0
        length = len(data)
        while index < length:
            char = data[index]
            if char == "\x1b":
                match = CSI.match(data, index)
                if match:
                    self._control(match.group(1), match.group(2))
                    index = match.end()
                    continue
                index += 1
                continue
            if char == "\n":
                self._newline()
            elif char == "\r":
                self.column = 0
            elif char == "\b":
                self.column = max(0, self.column - 1)
            elif char == "\t":
                self._put(" " * (8 - (self.column % 8)))
            elif char == "\x07":
                pass
            elif char < " " and char != "\x1b":
                pass
            else:
                run = index
                while run < length and data[run] >= " " and data[run] != "\x1b":
                    run += 1
                self._put(data[index:run])
                index = run
                continue
            index += 1
        self.revision += 1

    def _control(self, parameters: str, final: str) -> None:
        if final == "m":
            _apply_sgr(self.style, parameters)
            return
        numbers = [int(part) for part in parameters.split(";") if part.isdigit()]
        first = numbers[0] if numbers else 0
        if final == "K":                       # erase in line
            line = self._current()
            plain = self._plain(line)
            if first == 0:
                self._set_plain(line, plain[:self.column], self.style)
            elif first == 1:
                self._set_plain(line, " " * self.column + plain[self.column:], self.style)
            else:
                self._set_plain(line, "", self.style)
        elif final == "J":                     # erase in display
            if first in (2, 3):
                self.lines = [[]]
                self.column = 0
            else:
                del self.lines[len(self.lines):]
                self._set_plain(self._current(), self._plain(self._current())[:self.column], self.style)
        elif final in ("C", "D"):              # cursor right / left
            step = max(1, first)
            self.column = max(0, self.column + (step if final == "C" else -step))
        elif final == "G":
            self.column = max(0, (first or 1) - 1)
        elif final in ("A", "B", "H", "f"):
            # Vertical movement is not composited; keep the cursor sane.
            self.column = 0

    # ----------------------------------------------------------------- read
    def clear(self) -> None:
        self.lines = [[]]
        self.column = 0
        self.style = Style()
        self.revision += 1

    def rows(self) -> list[dict]:
        """The scrollback as QML-ready rows of styled spans."""
        output = []
        for number, line in enumerate(self.lines):
            spans = [{key: value for key, value in span.items() if key != "_key"}
                     for span in line if span["text"]]
            output.append({"index": number + self._dropped, "spans": spans,
                           "text": self._plain(line)})
        # A trailing empty line is the cursor's line, not content.
        if output and not output[-1]["text"]:
            output.pop()
        return output

    def plain_text(self) -> str:
        return "\n".join(self._plain(line) for line in self.lines).rstrip("\n")


class ShellSession:
    """One PTY-backed shell. Qt integration is injected, not imported."""

    def __init__(self, cwd: str = "", shell: str = "", env: dict | None = None):
        self.shell = shell or os.environ.get("SHELL") or "/bin/bash"
        self.cwd = str(cwd or Path.home())
        self.pid = 0
        self.fd = -1
        self.exit_code: int | None = None
        self.screen = AnsiScreen()
        self._env = env
        self._columns = 100
        self._rows = 30

    # --------------------------------------------------------------- state
    @property
    def running(self) -> bool:
        return self.pid > 0 and self.exit_code is None

    @property
    def shell_name(self) -> str:
        return Path(self.shell).name

    def start(self) -> None:
        if self.running:
            return
        directory = Path(self.cwd).expanduser()
        if not directory.is_dir():
            directory = Path.home()
        self.cwd = str(directory)

        import pty
        pid, fd = pty.fork()
        if pid == 0:                                   # child
            try:
                os.chdir(self.cwd)
                environment = dict(os.environ if self._env is None else self._env)
                environment["TERM"] = "xterm-256color"
                environment["COLORTERM"] = "truecolor"
                environment["COLUMNS"] = str(self._columns)
                environment["LINES"] = str(self._rows)
                # Wynxq's own Qt variables would leak into anything launched
                # from this shell; the shell should look like a login shell.
                for name in ("QT_QPA_PLATFORM", "QT_QUICK_BACKEND", "LD_PRELOAD"):
                    environment.pop(name, None)
                os.execvpe(self.shell, [self.shell, "-i"], environment)
            except Exception:
                os._exit(127)
        self.pid = pid
        self.fd = fd
        self.exit_code = None
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.resize(self._columns, self._rows)

    def resize(self, columns: int, rows: int) -> None:
        self._columns = max(20, min(int(columns or 80), 500))
        self._rows = max(5, min(int(rows or 24), 200))
        if self.fd < 0:
            return
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", self._rows, self._columns, 0, 0))
        except OSError:
            pass

    # ----------------------------------------------------------------- I/O
    def read(self) -> str:
        """Drain whatever the shell has produced. Returns '' when idle."""
        if self.fd < 0:
            return ""
        chunks = []
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            except OSError:
                self._reap()
                break
            if not data:
                self._reap()
                break
            chunks.append(data)
            if sum(len(chunk) for chunk in chunks) > 1_000_000:
                break
        if not chunks:
            return ""
        text = b"".join(chunks).decode("utf-8", "replace")
        self.screen.feed(text)
        return text

    def write(self, text: str) -> None:
        if self.fd < 0 or not self.running:
            return
        payload = str(text).encode("utf-8")
        while payload:
            try:
                written = os.write(self.fd, payload)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                self._reap()
                return
            payload = payload[written:]

    def send_line(self, command: str) -> None:
        self.write(str(command).rstrip("\n") + "\n")

    def interrupt(self) -> None:
        """Ctrl+C to the foreground group, exactly as a terminal would."""
        if not self.running:
            return
        try:
            group = os.tcgetpgrp(self.fd)
        except OSError:
            group = self.pid
        try:
            os.killpg(group, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def working_directory(self) -> str:
        """Where the shell actually is now, so the header cannot lie."""
        if not self.running:
            return self.cwd
        try:
            group = os.tcgetpgrp(self.fd)
        except OSError:
            group = self.pid
        for candidate in (group, self.pid):
            try:
                resolved = os.readlink(f"/proc/{candidate}/cwd")
            except OSError:
                continue
            if resolved:
                self.cwd = resolved
                return resolved
        return self.cwd

    def _reap(self) -> None:
        if self.pid <= 0:
            return
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.exit_code = self.exit_code if self.exit_code is not None else 0
            pid = self.pid
            status = 0
        if pid == self.pid:
            self.exit_code = os.waitstatus_to_exitcode(status) if status else 0
            self.close()

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1

    def stop(self) -> None:
        """End the session and everything it started."""
        if self.pid > 0:
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.killpg(os.getpgid(self.pid), sig)
                except (ProcessLookupError, PermissionError, OSError):
                    break
                try:
                    pid, status = os.waitpid(self.pid, os.WNOHANG)
                    if pid == self.pid:
                        self.exit_code = os.waitstatus_to_exitcode(status) if status else 0
                        break
                except ChildProcessError:
                    break
        self.close()
        if self.exit_code is None:
            self.exit_code = -1
        self.pid = 0
