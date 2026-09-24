"""Workspace-dock behavior slice bound onto DockController."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, QSocketNotifier, QTimer, Signal, Slot

from . import browser as browser_policy
from . import diffs
from . import project_files as files
from .activity import ActivityLog
from .terminal import ShellSession
from .dock_contract import DEFAULT_WIDTH, MAX_WIDTH, MIN_WIDTH, TABS, TAB_META
from .dock_models import FileTree, TerminalLines, _ORPHANED, _Worker

@Slot("QVariantMap")
def setTerminalPalette(self, palette):
    self.lines.set_palette(dict(palette or {}))
    if self._shell is not None:
        self.lines.sync(self._shell.screen.rows())


@Slot()
def startTerminal(self):
    if self._shell is not None and self._shell.running:
        return
    self._teardown_shell()
    session = ShellSession(cwd=self._project or str(Path.home()))
    try:
        session.start()
    except Exception as exc:
        self._shell_error = f"Could not start a shell: {exc}"
        self._terminal_started = True
        self.terminalChanged.emit()
        return
    self._shell = session
    self._shell_error = ""
    self._shell_cwd = session.cwd
    self._terminal_started = True
    self._notifier = QSocketNotifier(session.fd, QSocketNotifier.Read, self)
    self._notifier.activated.connect(self._drain_shell)
    self.terminalChanged.emit()


@Slot()
def restartTerminal(self):
    self._teardown_shell()
    self.lines.clear()
    self._terminal_started = False
    self.terminalChanged.emit()
    if self._visible and self._tab == "terminal":
        self.startTerminal()


def _teardown_shell(self) -> None:
    if self._notifier is not None:
        self._notifier.setEnabled(False)
        self._notifier.deleteLater()
        self._notifier = None
    if self._shell is not None:
        self._shell.stop()
        self._shell = None


def _drain_shell(self, *_):
    if self._shell is None:
        return
    produced = self._shell.read()
    if produced:
        self.lines.sync(self._shell.screen.rows())
    if not self._shell.running:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
        self.terminalChanged.emit()


def _poll_shell(self):
    if self._shell is None or not self._shell.running:
        return
    directory = self._shell.working_directory()
    if directory != self._shell_cwd:
        self._shell_cwd = directory
        self.terminalChanged.emit()


@Slot(str)
def sendTerminal(self, text):
    if self._shell is None or not self._shell.running:
        self.startTerminal()
    if self._shell is None:
        return
    self._shell.send_line(str(text))


@Slot(str)
def writeTerminal(self, text):
    if self._shell is not None:
        self._shell.write(str(text))


@Slot(str)
def runInTerminal(self, command):
    """Show a command in the terminal and run it there, opening the panel.

    Called from a menu the user opened, so it uses `openTab` rather than
    `suggest`: a suggestion is refused once a tab has been chosen by hand,
    and refusing to honour a click would be the wrong kind of consistent.
    """
    command = str(command or "").strip()
    if not command:
        return
    if self._tab != "terminal" or not self._visible:
        self._tab_pinned = True
        self._remember("dock_tab_pinned", True)
        self._select_tab("terminal")
        self.setVisible(True)
        self.changed.emit()
    self.startTerminal()
    self.sendTerminal(command)


@Slot()
def interruptTerminal(self):
    if self._shell is not None:
        self._shell.interrupt()


@Slot()
def clearTerminal(self):
    if self._shell is not None:
        self._shell.screen.clear()
    self.lines.clear()


@Slot(result=str)
def terminalText(self):
    return self._shell.screen.plain_text() if self._shell else ""


@Slot(int, int)
def resizeTerminal(self, columns, rows):
    if self._shell is not None:
        self._shell.resize(columns, rows)


__all__ = ['setTerminalPalette', 'startTerminal', 'restartTerminal', 'sendTerminal', 'writeTerminal', 'runInTerminal', 'interruptTerminal', 'clearTerminal', 'terminalText', 'resizeTerminal']
