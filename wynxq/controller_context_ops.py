"""Controller behavior slice.

This module contains implementation methods bound onto the public Controller
facade at class creation time. Keeping the Qt-facing API on Controller preserves
QML compatibility while separating unrelated responsibilities in source.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication

from . import context as ctx
from . import markdown as md
from . import notify
from . import system as system_info
from . import kwin
from .desktop import DesktopController
from .dock import DockController
from .agent_tools import (
    PERMISSION_DETAILS, PERMISSION_LABELS, PERMISSION_MODES, SAFE,
    action_summary, normalise_mode,
)
from .engine import AgentEngine, OllamaClient
from .memory import Memory
from .storage import Store
from .conversation import (
    GROUP_ORDER, STARTERS, TOOL_PRESENTATION, Messages, derive_title, group_for,
)
from .controller_support import (
    Job, _RunDesktop, _StoredTokens, _blank_metrics, _bounded_float,
    _bounded_int, _human_bytes,
)

def _add_attachment(self, attachment: dict):
    if len(self._attachments) >= 12:
        self.toast.emit("Twelve attachments is the limit for one message.")
        return
    self._attachments.append(attachment)
    self.attachmentsChanged.emit()
    self.changed.emit()


@Slot(str)
def removeAttachment(self, attachment_id):
    before = len(self._attachments)
    self._attachments = [item for item in self._attachments if item["id"] != attachment_id]
    if len(self._attachments) != before:
        self.attachmentsChanged.emit()
        self.changed.emit()


@Slot(str, bool)
def setAttachmentEnabled(self, attachment_id, enabled):
    attachment_id = str(attachment_id or "")
    enabled = bool(enabled)
    for index, item in enumerate(self._attachments):
        if str(item.get("id", "")) != attachment_id:
            continue
        if bool(item.get("enabled", True)) == enabled:
            return
        updated = dict(item)
        updated["enabled"] = enabled
        self._attachments[index] = updated
        self.attachmentsChanged.emit()
        self.changed.emit()
        return


def attach_web_page(self, page: dict) -> None:
    """Attach the page the browser is showing, on the user's request."""
    if not page or not page.get("text"):
        self.toast.emit("There is no readable text on that page yet.")
        return
    self._add_attachment(ctx.from_page(page))
    self.toast.emit(f"Attached {page.get('title') or 'the page'}")


@Slot()
def clearAttachments(self):
    if self._attachments:
        self._attachments = []
        self.attachmentsChanged.emit()
        self.changed.emit()


@Slot(str)
def attachPath(self, path):
    """Attach a dropped or picked path; folders and images are detected."""
    try:
        self._add_attachment(ctx.load_path(str(path).replace("file://", "")))
    except ctx.ContextError as exc:
        self._set_error("That file could not be attached", str(exc))
    except OSError as exc:
        self._set_error("That file could not be attached", str(exc))


@Slot()
def attachFile(self):
    from PySide6.QtWidgets import QFileDialog
    start = self._working_directory or ctx.default_directory()
    paths, _ = QFileDialog.getOpenFileNames(None, "Attach files", start, ctx.TEXT_FILTER)
    for path in paths:
        self.attachPath(path)


@Slot()
def attachFolder(self):
    from PySide6.QtWidgets import QFileDialog
    start = self._working_directory or ctx.default_directory()
    path = QFileDialog.getExistingDirectory(None, "Attach a folder", start)
    if path:
        self.attachPath(path)


@Slot()
def attachClipboard(self):
    clipboard = QGuiApplication.clipboard()
    image = clipboard.image()
    if not image.isNull():
        self.pasteImage()
        return
    try:
        self._add_attachment(ctx.from_clipboard(clipboard.text()))
    except ctx.ContextError as exc:
        self.toast.emit(str(exc))


def _attach_clipboard_png(self, image_png: bytes) -> bool:
    """Attach already-encoded clipboard pixels; split out for deterministic tests."""
    if not image_png:
        return False
    try:
        self._add_attachment(ctx.from_clipboard(image_png=bytes(image_png)))
    except ctx.ContextError as exc:
        self.toast.emit(str(exc))
        return False
    return True


@Slot(result=bool)
def pasteImage(self):
    from PySide6.QtCore import QBuffer, QByteArray
    image = QGuiApplication.clipboard().image()
    if image.isNull():
        return False
    buffer = QBuffer(QByteArray())
    buffer.open(QBuffer.WriteOnly)
    try:
        if not image.save(buffer, "PNG"):
            return False
        image_png = bytes(buffer.data())
    finally:
        buffer.close()
    return self._attach_clipboard_png(image_png)


@Slot(str)
def _navigate_builtin_browser(self, target):
    if not self.dock.browserAvailable:
        return
    self.dock.setTab("browser")
    if not self.dock.visible:
        self.dock.setVisible(True)
    self.dock.navigate(str(target))


def _request_builtin_browser(self, target: str) -> dict:
    """Worker-safe bridge from an agent tool into the GUI-owned browser."""
    from . import browser as browser_policy
    normalized = browser_policy.normalize(target)
    if not normalized:
        return {"ok": False, "error": "That is not a valid web address or search query"}
    if not self.dock.browserAvailable:
        return {"ok": False, "error": "Wynxq's built-in browser is unavailable"}
    self.browserNavigateRequested.emit(normalized)
    return {"ok": True, "url": normalized, "browser": "Wynxq built-in browser"}


def _request_builtin_browser_for(self, task_id: str, target: str) -> dict:
    if str(task_id or "") != self._task_id:
        return {"ok": False, "error":
                "The built-in browser is foreground-only. Open this chat to navigate it."}
    return self._request_builtin_browser(target)


def _capture(self, kind: str):
    if self._capture_busy:
        return
    self._capture_busy = True
    self.changed.emit()

    def done(result):
        self._capture_busy = False
        try:
            title = "Active window" if kind == "window" else "Screen"
            self._add_attachment(ctx.from_capture(result, ctx.WINDOW if kind == "window" else ctx.SCREENSHOT,
                                                  title=result.get("detail") or title,
                                                  detail=result.get("detail", "")))
        except ctx.ContextError as exc:
            self._set_error("Screen capture failed", str(exc))
        self.changed.emit()

    def failed(message):
        self._capture_busy = False
        self._set_error("Screen capture failed", message,
                        [{"label": "Desktop settings", "action": "desktop"}])

    self._job(lambda cancel, emit: self.desktop.capture(kind, cancel), done, failed)


@Slot()
def attachScreenshot(self):
    self._capture("screen")


@Slot()
def attachRegion(self):
    """Capture the screen, then let the user pick part of it.

    The crop happens here, on an image Wynxq already holds, so selecting a
    region needs no extra permission and nothing new is captured.
    """
    if self._capture_busy or self._region.get("image"):
        return
    self._capture_busy = True
    self.changed.emit()

    def done(result):
        self._capture_busy = False
        if result.get("ok") and result.get("image"):
            self._region = {"image": result["image"], "width": result.get("width", 0),
                            "height": result.get("height", 0)}
            self.regionChanged.emit()
        else:
            self._set_error("Screen capture failed", result.get("error", "No image was returned."))
        self.changed.emit()

    def failed(message):
        self._capture_busy = False
        self._set_error("Screen capture failed", message,
                        [{"label": "Desktop settings", "action": "desktop"}])

    self._job(lambda cancel, emit: self.desktop.capture("screen", cancel), done, failed)


@Slot()
def cancelRegion(self):
    if self._region.get("image"):
        self._region = {}
        self.regionChanged.emit()


@Slot(int, int, int, int)
def cropRegion(self, x, y, width, height):
    image = self._region.get("image", "")
    self._region = {}
    self.regionChanged.emit()
    if not image or width < 8 or height < 8:
        return
    try:
        import base64
        import io
        from PIL import Image
        with Image.open(io.BytesIO(base64.b64decode(image))) as picture:
            box = (max(0, x), max(0, y),
                   min(picture.width, x + width), min(picture.height, y + height))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                return
            cropped = picture.crop(box).convert("RGB")
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:
        self._set_error("That region could not be cropped", str(exc))
        return
    self._add_attachment(ctx.from_capture(
        {"ok": True, "image": encoded, "width": cropped.width, "height": cropped.height},
        ctx.SCREENSHOT, title="Screen region", detail="Region"))


@Slot()
def attachWindow(self):
    self._capture("window")


@Slot(result=str)
def activeWindowTitle(self):
    return str(self.desktop.active_window().get("title", ""))


def _set_project(self, path: str):
    """Move to a folder, remembering where we have been."""
    path = str(path or "")
    self._working_directory = path
    self.store.set_setting("working_directory", path)
    if path:
        self._recent_projects = [path] + [p for p in self._recent_projects if p != path]
        del self._recent_projects[self.RECENT_PROJECT_LIMIT:]
        self.store.set_setting("recent_projects", self._recent_projects)
    self.dock.set_project(path)
    if path:
        # Opening a project is the one moment where Files is obviously the
        # useful panel. It is still only a suggestion: a tab the user has
        # chosen by hand is never replaced.
        self.dock.suggest("files")
    self.changed.emit()


@Slot()
def chooseProject(self):
    from PySide6.QtWidgets import QFileDialog
    start = self._working_directory or ctx.default_directory()
    path = QFileDialog.getExistingDirectory(None, "Choose a project folder", start)
    if path:
        self._set_project(path)
        self.toast.emit(f"Working in {ctx.working_directory_label(path)}")


@Slot(str)
def openProject(self, path):
    """Return to a folder from the recent list."""
    path = str(path or "")
    if not path or not Path(path).is_dir():
        self._recent_projects = [p for p in self._recent_projects if p != path]
        self.store.set_setting("recent_projects", self._recent_projects)
        self.changed.emit()
        self.toast.emit("That folder is no longer there.")
        return
    self._set_project(path)


@Slot()
def clearProject(self):
    self._set_project("")


@Slot()
def copyProjectPath(self):
    if self._working_directory:
        self.copyText(self._working_directory)
    else:
        self.toast.emit("No project folder is set.")


@Slot(str)
def revealPath(self, path):
    target = str(path) or self._working_directory
    if not target or not notify.open_path(target):
        self.toast.emit("No file manager is available to open that location.")


@Slot()
def openTerminalHere(self):
    if not notify.open_terminal(self._working_directory or str(Path.home())):
        self.toast.emit("No terminal emulator was found on this system.")
