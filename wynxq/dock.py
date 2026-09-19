"""The workspace dock: the tools on the right-hand side of the window.

One QObject per concern, assembled here and exposed to QML as `bridge.dock`.
The main controller stays about the conversation; the dock owns Files,
Terminal, Changes, Context, Memory, Activity, Browser and Preview.

Three rules shape everything below:

* Nothing blocks the GUI thread. The shell is read from a socket notifier;
  Git runs on a worker; the file tree is loaded one level at a time.
* The dock never moves the panel the user is looking at. It may *open* itself
  and it may suggest a tab, but a tab the user selected by hand is theirs until
  they change it.
* Every path is proved to be inside the project before it reaches the UI.
"""
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
from . import dock_layout_ops as _layout_ops
from . import dock_file_ops as _file_ops
from . import dock_terminal_ops as _terminal_ops
from . import dock_change_ops as _change_ops
from . import dock_context_ops as _context_ops
from . import dock_browser_ops as _browser_ops


class DockController(QObject):
    """Everything the right-hand workspace needs, and nothing else."""

    changed = Signal()
    filesChanged = Signal()
    viewerChanged = Signal()
    terminalChanged = Signal()
    changesChanged = Signal()
    contextChanged = Signal()
    activityChanged = Signal()
    browserChanged = Signal()
    previewChanged = Signal()
    revealRow = Signal(int)
    toast = Signal(str)

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._owner = parent
        setting = store.get_setting if store else (lambda key, default=None: default)

        self._visible = bool(setting("dock_visible", False))
        self._width = max(MIN_WIDTH, min(int(setting("dock_width", DEFAULT_WIDTH) or DEFAULT_WIDTH), MAX_WIDTH))
        tab = str(setting("dock_tab", "files") or "files")
        self._tab = tab if tab in TABS else "files"
        stored_order = setting("dock_tab_order", []) or []
        self._tab_order = []
        for name in stored_order:
            name = str(name)
            if name in TABS and name not in self._tab_order:
                self._tab_order.append(name)
        self._tab_order.extend(name for name in TABS if name not in self._tab_order)
        self._hidden_tabs = {str(name) for name in (setting("dock_hidden_tabs", []) or [])
                             if str(name) in TABS}
        if len(self._hidden_tabs) >= len(TABS):
            self._hidden_tabs.clear()
        # Set the moment the user clicks a tab. While it is set, nothing in the
        # app is allowed to change the visible panel underneath them.
        self._tab_pinned = bool(setting("dock_tab_pinned", False))
        self._project = ""

        self.tree = FileTree(self)
        self.tree.set_show_hidden(bool(setting("dock_show_hidden", False)))
        self.tree.changed.connect(self.filesChanged)
        self._file_filter = ""
        self._search_results: list[dict] = []
        self._search_generation = 0
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(120)
        self._search_debounce.timeout.connect(self._start_file_search)

        self._viewer: dict = {}
        self._viewer_buffer = ""
        self._viewer_dirty = False

        self.lines = TerminalLines(self)
        self._shell: ShellSession | None = None
        self._notifier: QSocketNotifier | None = None
        self._shell_cwd = ""
        self._shell_error = ""
        self._terminal_started = False

        self._changes: dict = {"repository": False, "branch": "", "files": [],
                               "added": 0, "removed": 0, "error": ""}
        self._change_path = ""
        self._diff: dict = {"rows": [], "error": "", "path": "", "binary": False}
        self._changes_busy = False
        self._workers: set[_Worker] = set()
        self._worker_queue: list[_Worker] = []
        self._active_worker: _Worker | None = None

        self.log = ActivityLog()
        self._activity_revision = -1

        self._browser_url = ""
        self._browser_pending = ""
        self._browser_title = ""
        self._browser_loading = False
        self._browser_progress = 0.0
        self._browser_can_back = False
        self._browser_can_forward = False
        self._browser_error = ""

        self._preview: dict = {}

        # One cheap poll while the terminal is on screen keeps the header's
        # working directory honest without a timer per panel.
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self._poll_shell)


    # ------------------------------------------------ behavior slices
    # Public QML properties stay on this facade; operational behavior is split
    # by concern so Files, Terminal, Git, Context, and Browser can evolve alone.
    # dock layout/project operations
    moveTab = _layout_ops.moveTab
    setTabHidden = _layout_ops.setTabHidden
    resetTabLayout = _layout_ops.resetTabLayout
    _remember = _layout_ops._remember
    setVisible = _layout_ops.setVisible
    toggle = _layout_ops.toggle
    setWidth = _layout_ops.setWidth
    setTab = _layout_ops.setTab
    openTab = _layout_ops.openTab
    _select_tab = _layout_ops._select_tab
    suggest = _layout_ops.suggest
    _on_tab_shown = _layout_ops._on_tab_shown
    _block_dirty_transition = _layout_ops._block_dirty_transition
    set_project = _layout_ops.set_project

    # dock file operations
    setShowHidden = _file_ops.setShowHidden
    setFileFilter = _file_ops.setFileFilter
    _start_file_search = _file_ops._start_file_search
    refreshFiles = _file_ops.refreshFiles
    toggleFolder = _file_ops.toggleFolder
    revealFile = _file_ops.revealFile
    openFile = _file_ops.openFile
    closeFile = _file_ops.closeFile
    setFileBuffer = _file_ops.setFileBuffer
    saveFile = _file_ops.saveFile
    revertFileBuffer = _file_ops.revertFileBuffer

    # dock terminal operations
    setTerminalPalette = _terminal_ops.setTerminalPalette
    startTerminal = _terminal_ops.startTerminal
    restartTerminal = _terminal_ops.restartTerminal
    _teardown_shell = _terminal_ops._teardown_shell
    _drain_shell = _terminal_ops._drain_shell
    _poll_shell = _terminal_ops._poll_shell
    sendTerminal = _terminal_ops.sendTerminal
    writeTerminal = _terminal_ops.writeTerminal
    runInTerminal = _terminal_ops.runInTerminal
    interruptTerminal = _terminal_ops.interruptTerminal
    clearTerminal = _terminal_ops.clearTerminal
    terminalText = _terminal_ops.terminalText
    resizeTerminal = _terminal_ops.resizeTerminal

    # dock Git change operations
    _run = _change_ops._run
    _start_next_worker = _change_ops._start_next_worker
    _deliver = _change_ops._deliver
    _deliver_failure = _change_ops._deliver_failure
    _retire_worker = _change_ops._retire_worker
    refreshChanges = _change_ops.refreshChanges
    openDiff = _change_ops.openDiff
    closeDiff = _change_ops.closeDiff
    revertChange = _change_ops.revertChange
    absolutePath = _change_ops.absolutePath

    # dock context/activity operations
    removeContext = _context_ops.removeContext
    refresh_context = _context_ops.refresh_context
    clearActivity = _context_ops.clearActivity
    record = _context_ops.record
    record_update = _context_ops.record_update
    begin_turn = _context_ops.begin_turn
    settle_turn = _context_ops.settle_turn

    # dock browser/preview lifecycle operations
    navigate = _browser_ops.navigate
    browserStateChanged = _browser_ops.browserStateChanged
    browserLoadState = _browser_ops.browserLoadState
    browserHistoryState = _browser_ops.browserHistoryState
    browserFailed = _browser_ops.browserFailed
    clearBrowser = _browser_ops.clearBrowser
    attachPage = _browser_ops.attachPage
    showPreview = _browser_ops.showPreview
    clearPreview = _browser_ops.clearPreview
    shutdown = _browser_ops.shutdown

    # ------------------------------------------------------------ shell state
    @Property(bool, notify=changed)
    def visible(self):
        return self._visible

    @Property(int, notify=changed)
    def width(self):
        return self._width

    @Property(str, notify=changed)
    def tab(self):
        return self._tab

    @Property("QVariantList", notify=changed)
    def tabs(self):
        return [{"id": name, **TAB_META[name]}
                for name in self._tab_order if name not in self._hidden_tabs]

    @Property(int, constant=True)
    def minimumWidth(self):
        return MIN_WIDTH

    @Property(int, constant=True)
    def maximumWidth(self):
        return MAX_WIDTH

    # ----------------------------------------------------------- the project
    @Property(str, notify=changed)
    def projectPath(self):
        return self._project

    @Property(str, notify=changed)
    def projectName(self):
        return Path(self._project).name if self._project else ""

    # ---------------------------------------------------------------- files
    @Property(QObject, constant=True)
    def fileModel(self):
        return self.tree

    @Property(bool, notify=filesChanged)
    def showHidden(self):
        return self.tree.show_hidden

    @Property(str, notify=filesChanged)
    def fileFilter(self):
        return self._file_filter

    @Property("QVariantList", notify=filesChanged)
    def fileMatches(self):
        return self._search_results

    @Property(str, notify=filesChanged)
    def fileError(self):
        return self.tree.error

    # --------------------------------------------------------- file viewer
    @Property("QVariantMap", notify=viewerChanged)
    def file(self):
        return dict(self._viewer)

    @Property(str, notify=viewerChanged)
    def filePath(self):
        return str(self._viewer.get("path", ""))

    @Property(bool, notify=viewerChanged)
    def fileModified(self):
        return self._viewer_dirty

    # -------------------------------------------------------------- terminal
    @Property(QObject, constant=True)
    def terminalModel(self):
        return self.lines

    @Property(bool, notify=terminalChanged)
    def terminalRunning(self):
        return bool(self._shell and self._shell.running)

    @Property(str, notify=terminalChanged)
    def terminalShell(self):
        return self._shell.shell_name if self._shell else ""

    @Property(str, notify=terminalChanged)
    def terminalDirectory(self):
        return self._shell_cwd

    @Property(str, notify=terminalChanged)
    def terminalDirectoryLabel(self):
        path = self._shell_cwd or self._project
        if not path:
            return ""
        try:
            home = str(Path.home())
            return "~" + path[len(home):] if path.startswith(home) else path
        except (OSError, RuntimeError):
            return path

    @Property(str, notify=terminalChanged)
    def terminalError(self):
        return self._shell_error

    @Property(bool, notify=terminalChanged)
    def terminalStarted(self):
        return self._terminal_started

    # --------------------------------------------------------------- changes
    @Property("QVariantList", notify=changesChanged)
    def changes(self):
        return self._changes.get("files", [])

    @Property(bool, notify=changesChanged)
    def isRepository(self):
        return bool(self._changes.get("repository"))

    @Property(str, notify=changesChanged)
    def branch(self):
        return str(self._changes.get("branch", ""))

    @Property(str, notify=changesChanged)
    def changesSummary(self):
        entries = self._changes.get("files", [])
        if not entries:
            return "No uncommitted changes"
        count = f"{len(entries)} file" + ("" if len(entries) == 1 else "s")
        return f"{count} · +{self._changes.get('added', 0)} −{self._changes.get('removed', 0)}"

    @Property(str, notify=changesChanged)
    def changesError(self):
        return str(self._changes.get("error", ""))

    @Property(bool, notify=changesChanged)
    def changesBusy(self):
        return self._changes_busy

    @Property(str, notify=changesChanged)
    def diffPath(self):
        return self._change_path

    @Property("QVariantList", notify=changesChanged)
    def diffRows(self):
        return self._diff.get("rows", [])

    @Property(str, notify=changesChanged)
    def diffError(self):
        return str(self._diff.get("error", ""))

    # --------------------------------------------------------------- context
    @Property("QVariantList", notify=contextChanged)
    def contextItems(self):
        """What the model can currently see, grouped for the Context panel.

        Composed from the controller's real state — attachments, the project,
        the open file, the browser — rather than a second store that could
        disagree with the composer.
        """
        groups: list[dict] = []
        owner = self._owner

        if self._project:
            groups.append({"title": "Workspace", "icon": "folderOpen", "items": [{
                "id": "project", "label": Path(self._project).name,
                "detail": self._project, "removable": False, "kind": "folder",
            }]})

        attachments = list(getattr(owner, "_attachments", []) or []) if owner else []
        if attachments:
            groups.append({"title": "Attached", "icon": "paperclip", "items": [{
                "id": "attachment:" + str(item.get("id", "")),
                "label": str(item.get("title", "")),
                "detail": str(item.get("subtitle", "")),
                "removable": True,
                "kind": str(item.get("kind", "file")),
                "tokens": int(item.get("tokens", 0) or 0),
            } for item in attachments]})

        if self._viewer.get("path"):
            groups.append({"title": "Open file", "icon": "file", "items": [{
                "id": "file", "label": self._viewer.get("name", ""),
                "detail": self._viewer.get("relative", ""),
                "removable": True, "kind": "file",
                "tokens": 0,
            }]})

        if self._browser_url:
            groups.append({"title": "Browser", "icon": "globe", "items": [{
                "id": "browser", "label": self._browser_title or browser_policy.display_url(self._browser_url),
                "detail": browser_policy.display_url(self._browser_url),
                "removable": True, "kind": "link",
            }]})

        changed = self._changes.get("files", [])
        if changed:
            groups.append({"title": "Changed files", "icon": "branch", "items": [{
                "id": "change:" + entry["path"], "label": entry["name"],
                "detail": f"+{entry['added']} −{entry['removed']}",
                "removable": False, "kind": "diff",
            } for entry in changed[:12]]})

        return groups

    # -------------------------------------------------------------- activity
    @Property("QVariantList", notify=activityChanged)
    def activityRows(self):
        return self.log.rows()

    @Property(str, notify=activityChanged)
    def activitySummary(self):
        return self.log.summary()

    @Property(bool, notify=activityChanged)
    def activityRunning(self):
        return self.log.running

    # --------------------------------------------------------------- browser
    @Property(bool, constant=True)
    def browserAvailable(self):
        return browser_policy.engine_available()

    @Property(str, constant=True)
    def browserUnavailableReason(self):
        return browser_policy.unavailable_reason()

    @Property(str, constant=True)
    def browserHome(self):
        return browser_policy.DEFAULT_HOME

    @Property(str, notify=browserChanged)
    def browserUrl(self):
        return self._browser_url

    @Property(str, notify=browserChanged)
    def browserRequest(self):
        return self._browser_pending

    @Property(str, notify=browserChanged)
    def browserDisplayUrl(self):
        return browser_policy.display_url(self._browser_url)

    @Property(str, notify=browserChanged)
    def browserTitle(self):
        return self._browser_title

    @Property(bool, notify=browserChanged)
    def browserLoading(self):
        return self._browser_loading

    @Property(float, notify=browserChanged)
    def browserProgress(self):
        return self._browser_progress

    @Property(bool, notify=browserChanged)
    def browserSecure(self):
        return browser_policy.is_secure(self._browser_url)

    @Property(str, notify=browserChanged)
    def browserTrust(self):
        """"secure", "local" or "insecure" — what the address bar's mark means."""
        if not self._browser_url:
            return ""
        if browser_policy.is_secure(self._browser_url):
            return "secure"
        return "local" if browser_policy.is_local(self._browser_url) else "insecure"

    @Property(str, notify=browserChanged)
    def browserError(self):
        return self._browser_error

    @Property(bool, notify=browserChanged)
    def browserCanGoBack(self):
        return self._browser_can_back

    @Property(bool, notify=browserChanged)
    def browserCanGoForward(self):
        return self._browser_can_forward

    # --------------------------------------------------------------- preview
    @Property("QVariantMap", notify=previewChanged)
    def preview(self):
        return dict(self._preview)

    # ------------------------------------------------------------- lifecycle