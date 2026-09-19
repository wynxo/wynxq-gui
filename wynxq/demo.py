"""Deterministic demo state for UI previews and screenshots.

``python -m wynxq --ui-preview`` and ``--snapshot`` run the real QML with a
controller whose backend calls are replaced by fixed data. Nothing here touches
the user's history, Ollama, or the desktop: it exists so screenshots show the
actual renderer rather than a mock-up.
"""
from __future__ import annotations

import http.server
import socketserver
import tempfile
import threading
import time
from pathlib import Path

from . import context as ctx
from . import markdown as md
from .memory import Memory
from .storage import Store
from .workspace import WorkspaceController

ANSWER = """**Firefox** is focused, with `pytest` running in a terminal behind it.
Two tests fail on the same assertion.

### What's failing

| Test | Reason |
| --- | --- |
| `test_context_window` | expected 8192, got 16384 |
| `test_keep_alive` | keep-alive not forwarded |

Same root cause: the options are built before the preset is applied.

```python
def build_options(preset: str, overrides: dict) -> dict:
    # Apply the preset first, then let explicit overrides win.
    options = dict(PRESETS[preset])
    options.update({k: v for k, v in overrides.items() if v is not None})
    return options
```

Want me to open the file and make the change?"""

THINKING = """The user asked what is on screen. I have a screenshot, so I should
describe what is actually visible rather than guess. Two failing tests are
readable in the terminal pane. Both mention runtime options, so the likely cause
is ordering in the options builder. I will summarise, then offer to edit rather
than editing without being asked."""

# title, age in seconds, pinned, mode. The mode is what the sidebar marks, so
# the screenshots have to include both kinds of task.
CONVERSATIONS = [
    ("Debug the failing runtime tests", 0, True, "work"),
    ("Draw a mountain scene in KolourPaint", 2400, False, "work"),
    ("Summarise this design document", 9000, False, "chat"),
    ("Rewrite the composer layout", 26 * 3600, False, "work"),
    ("Plan the 1.0 release", 30 * 3600, False, "chat"),
    ("Rename the screenshots folder", 32 * 3600, False, "work"),
    ("Explain this stack trace", 5 * 86400, False, "chat"),
    ("Compare two CSV exports", 12 * 86400, False, "chat"),
    ("Set up a Python project", 40 * 86400, False, "work"),
]

CATALOG = [
    {"name": "qwen2.5vl:7b", "family": "qwen2vl", "parameters": "7.6B", "quantization": "Q4_K_M",
     "sizeLabel": "5.6 GB", "sizeBytes": 6_000_000_000, "capabilities": ["completion", "tools", "vision"],
     "favorite": True, "loaded": True, "selected": True},
    {"name": "gemma3:4b", "family": "gemma3", "parameters": "4.3B", "quantization": "Q4_K_M",
     "sizeLabel": "3.3 GB", "sizeBytes": 3_500_000_000, "capabilities": ["completion", "vision"],
     "favorite": True, "loaded": False, "selected": False},
    {"name": "llama3.2:3b", "family": "llama", "parameters": "3.2B", "quantization": "Q4_K_M",
     "sizeLabel": "2.0 GB", "sizeBytes": 2_100_000_000, "capabilities": ["completion", "tools"],
     "favorite": False, "loaded": False, "selected": False},
    {"name": "qwen3:8b", "family": "qwen3", "parameters": "8.2B", "quantization": "Q4_K_M",
     "sizeLabel": "5.2 GB", "sizeBytes": 5_400_000_000, "capabilities": ["completion", "tools", "thinking"],
     "favorite": False, "loaded": False, "selected": False},
    {"name": "deepseek-r1:7b", "family": "qwen2", "parameters": "7.6B", "quantization": "Q4_K_M",
     "sizeLabel": "4.7 GB", "sizeBytes": 4_900_000_000, "capabilities": ["completion", "thinking"],
     "favorite": False, "loaded": False, "selected": False},
    {"name": "nomic-embed-text:latest", "family": "nomic-bert", "parameters": "137M",
     "quantization": "F16", "sizeLabel": "274 MB", "sizeBytes": 274_000_000,
     "capabilities": ["embedding"], "favorite": False, "loaded": False, "selected": False},
]

_SWATCH = (
    "iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAAC8UlEQVR42u3csWrbQBzAYblodp0ORghjTJ8sQ56gY4c+"
    "Qp6gQ5+sGGOM8VIwwXOGQEhbN8W2pLv76/umEJNCjv64O90pk7ZdVkCZPhgCEDAgYOAS9dnvrlafX75Yr392+ynQ7wz8"
    "WuAfX9/+KdBvwN0Wq2GwBwYEDOED/vvJ09vv3PIpMMQM3FWx6oW+TVylBHtgQMCAgGEk6tPpySiAGRgQMCBgEDAgYEDA"
    "gIBBwICAAQGDgAEBAwIGBAwCBgQMCBgQMARQX/dji8XK2HVlu11f+iPT6Z1xi+d4/DVQwFVVHQ57I367+bwxCFhCg4AB"
    "AQMCBgQMAgYEDAgYEDAIGEim7uMfXS5X8UZqs1n774IZGBAwIGAQMJBGbQhKNJ1+3O93xiGSpmmveKHfDAxm4N85cQF7"
    "YEDAIGBAwICAAQGDgAEBA5dzlTKsH98fY/+CX7/l/gvudtsiAw7wQr/LZFhCAwIGBAzxeIgV1v3DF4NgBgYEDJSyhHYG"
    "A2ZgQMAgYGAse2By0LYLg/AvA9xSNgMDAgYBAwIGuuQhVlhhntMwdMDFvdDv6hiW0ICAAQGDgAEBA/1wjBRWoXehnX6l"
    "D9ipDFhCAwIGAQNj2QOTA0+DzMCAgAEBAwIGAQMZGOML/S6KIWBy5+9CJzfASZ4lNNgDAwIGBAxj4SFWWO5CC/hKzmnA"
    "EhoQMAgYEDAgYKCqKsdIgbkL/Y4wZ2xmYBAwIGAg/R44qxf6XQtDwJTHXWhLaEDAgIABAYOAgQx4oR8ETH4KvQvt9MsS"
    "GgQMCBgQMHCGh1hheRpkBgYEDAgYGGIPnPCFfpfAMAMDAgZKXEKTA38XOrkBTvLMwGAJDQgYSL8HdpYDBQdMDtyFtoQG"
    "BAwIGBAwCBgQMCBgEDAgYEDAwP9df5VyPm8MX0JN0xoEJrPZJ6MAltCAgAEBg4ABAQMCBgQMAgYEDAgYBAwIGBAwIGAQ"
    "MCBgQMCAgEHAgIABAYOAAQEDAgYEDAIGBAwIGKieAdhQjRZgDb/uAAAAAElFTkSuQmCC"
)

STEPS = [
    {"name": "screenshot", "icon": "eye", "label": "Inspecting the screen",
     "summary": "Capture the screen", "detail": "{}", "state": "done", "ms": 640,
     "output": "Captured 2560 × 1440 pixels", "risk": "low"},
    {"name": "list_apps", "icon": "grid", "label": "Listing installed apps",
     "summary": "List installed applications", "detail": "{}", "state": "done", "ms": 210,
     "output": "182 applications found", "risk": "low"},
    {"name": "open_app", "icon": "launch", "label": "Opening an application",
     "summary": "Open KolourPaint", "detail": '{"app": "org.kde.kolourpaint"}',
     "state": "done", "ms": 1480, "output": "", "risk": "normal"},
    {"name": "wait", "icon": "clock", "label": "Waiting",
     "summary": "Wait 1.5s", "detail": '{"seconds": 1.5}', "state": "done", "ms": 1500,
     "output": "", "risk": "low"},
    {"name": "click", "icon": "cursor", "label": "Clicking",
     "summary": "Click the left button at 512, 336", "detail": '{"x": 512, "y": 336}',
     "state": "done", "ms": 180, "output": "", "risk": "normal"},
    {"name": "drag", "icon": "paint", "label": "Dragging",
     "summary": "Drag through 24 points", "detail": '{"points": [[420, 620], [512, 470]], "duration": 1.4}',
     "state": "done", "ms": 1420, "output": "", "risk": "normal"},
    {"name": "type_text", "icon": "keyboard", "label": "Typing",
     "summary": "Type “mountains.png”", "detail": '{"text": "mountains.png"}',
     "state": "waiting", "ms": 0, "output": "", "risk": "sensitive"},
]


# A project run: read, search, edit, then a real command with real output.
# This is the shape §19 of the redesign asks for, so the screenshot has to be
# of that shape rather than of a desktop run.
CODE_STEPS = [
    {"name": "read_file", "icon": "file", "label": "Reading a file",
     "summary": "Read wynxq/ui/Wynxq/Composer.qml", "detail": '{"path": "wynxq/ui/Wynxq/Composer.qml"}',
     "state": "done", "ms": 90, "output": "403 lines", "risk": "low"},
    {"name": "search", "icon": "search", "label": "Searching the project",
     "summary": "Search for “maxHeight”", "detail": '{"pattern": "maxHeight"}',
     "state": "done", "ms": 240, "output": "3 matches in 2 files", "risk": "low"},
    {"name": "edit_file", "icon": "edit", "label": "Editing a file",
     "summary": "Edit wynxq/ui/Wynxq/Composer.qml", "detail": '{"path": "wynxq/ui/Wynxq/Composer.qml"}',
     "state": "done", "ms": 130, "output": "+6 −6", "risk": "normal"},
    {"name": "run_command", "icon": "terminal", "label": "Running a command",
     "summary": "python -m pytest tests/test_ui_assets.py -q",
     "detail": '{"command": "python -m pytest tests/test_ui_assets.py -q", "cwd": "."}',
     "state": "done", "ms": 4120, "risk": "normal",
     "output": "..............................\n30 passed in 1.35s"},
]


# The Browser scene loads a real page over real HTTP from a real server, so the
# screenshot is of Qt WebEngine rendering rather than of an empty state. Local
# and self-contained: the snapshot job needs no network.
PREVIEW_PAGE = b"""<!doctype html><meta charset="utf-8"><title>Wynxq GUI \xe2\x80\x94 local browsing</title>
<style>
 :root{color-scheme:dark}
 body{font:15px/1.65 system-ui,sans-serif;background:#191919;color:#f2f1ed;margin:0;padding:28px 26px}
 h1{font-size:21px;margin:0 0 6px;letter-spacing:-.3px}
 p.lede{color:#97968f;margin:0 0 20px;font-size:13px}
 h2{font-size:13px;color:#c6c5bf;margin:22px 0 8px;font-weight:600}
 ul{margin:0;padding-left:18px;color:#c6c5bf}
 li{margin:5px 0}
 code{background:#0e0e0e;color:#d8d7d2;padding:1px 5px;border-radius:4px;font:12px ui-monospace,monospace}
 .note{border-left:2px solid #df7e5e;padding:2px 0 2px 12px;margin-top:22px;color:#97968f;font-size:13px}
</style>
<h1>Local browsing</h1>
<p class="lede">Served over HTTP from this machine and rendered by Qt WebEngine.</p>
<h2>What the panel does</h2>
<ul>
 <li>The address bar shows where you actually are</li>
 <li>Back and forward follow real history</li>
 <li><code>http</code> and <code>https</code> only \xe2\x80\x94 nothing else is opened</li>
 <li>Pop-ups and permission requests are refused</li>
</ul>
<h2>And the model</h2>
<ul>
 <li>Sees nothing here until you attach the page</li>
 <li>Gets it as untrusted text, labelled with its address</li>
</ul>
<p class="note">Read a doc beside the task instead of leaving Wynxq GUI to find it.</p>
"""


class _PreviewPage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PREVIEW_PAGE)))
        self.end_headers()
        self.wfile.write(PREVIEW_PAGE)

    def log_message(self, *arguments):
        pass


def serve_preview_page():
    """Start a loopback server for the Browser scene. Returns its URL."""
    server = socketserver.TCPServer(("127.0.0.1", 0), _PreviewPage)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


class DemoDesktop:
    def __init__(self, connected: bool = True):
        self.connected = connected

    def status(self):
        return {"backend": "Wayland / Desktop portal", "available": True,
                "connected": self.connected,
                "detail": "Connected through the desktop portal. Screenshot permission is managed separately by your desktop.",
                "remembered": self.connected,
                "stopShortcut": "Ctrl+Alt+Esc" if self.connected else "", "stopDetail": ""}

    def connect(self):
        self.connected = True
        return self.status()

    def disconnect(self):
        self.connected = False

    def capture(self, kind="screen", cancel=None):
        raise RuntimeError("Screen capture is disabled in preview mode.")

    def active_window(self):
        return {"title": "Firefox", "detail": "X11"}


class DemoController(WorkspaceController):
    """The real task-scoped controller with network and desktop edges pinned."""

    def __init__(self, scene: str = "conversation"):
        directory = tempfile.mkdtemp(prefix="wynxq-preview-")
        store = Store(Path(directory) / "preview.sqlite3")
        store.set_setting("onboarded", scene != "welcome")
        store.set_setting("model", "qwen2.5vl:7b")
        store.set_setting("permission_mode", "safe")
        store.set_setting("favorite_models", [entry["name"] for entry in CATALOG if entry["favorite"]])
        theme = {"empty-violet": "Violet", "empty-ember": "Ember", "conversation-ion": "Ion"}.get(scene)
        if theme:
            store.set_setting("theme", theme)
        connected = scene in ("desktop", "conversation", "run", "usage", "empty-work-locked")
        # A preview must never read or write the real memory file.
        super().__init__(store=store, desktop=DemoDesktop(connected), autoconnect=False,
                         memory=Memory(Path(directory) / "memory.md"))
        self._preview_directory = Path(directory)
        self._page_server = None
        self.scene = scene
        self._seed()
        self._seed_memory()

    def _seed_memory(self):
        """Plausible notes, so the Memory panel shows memory rather than a shrug.

        Seeded after the scene so the project section matches the folder the
        preview actually opened.
        """
        for note in ("Prefers short answers with the command first, the explanation after",
                     "Runs NixOS; installs nothing with apt",
                     "Ollama lives on the homelab box at 192.168.1.50"):
            self.memory.remember(note)
        for note in ("Tests are pytest, run from the repository root",
                     "The QML shell is loaded from wynxq/ui; qmldir must list every component"):
            self.memory.remember(note, scope="project", project=self._working_directory)
        self.memoryChanged.emit()

    def refreshModels(self):
        self._apply_catalog()

    def _apply_catalog(self):
        self._online = True
        self._probe_active = False
        self._models = [entry["name"] for entry in CATALOG]
        self._catalog = [dict(entry) for entry in CATALOG]
        self._loaded_models = [entry["name"] for entry in CATALOG if entry["loaded"]]
        self._model_capabilities = ["completion", "tools", "vision"]
        self._model_context_length = 128000
        self._capability_probe_active = False
        self._clear_error()
        self._decorate_catalog()
        self.changed.emit()

    def _seed(self):
        now = time.time()
        created = []
        for title, age, pinned, mode in CONVERSATIONS:
            conversation = self.store.create_conversation(title, "qwen2.5vl:7b")
            self.store.set_messages(conversation["id"], [{"role": "user", "content": title}])
            self.store.set_setting(self._mode_key(conversation["id"]), mode)
            with self.store._lock, self.store._db:
                self.store._db.execute("UPDATE conversations SET updated_at=?,created_at=?,pinned=? WHERE id=?",
                                       (now - age, now - age, 1 if pinned else 0, conversation["id"]))
            created.append(conversation)
        self._apply_catalog()
        self._refresh_tasks()

        # The dock panels read a real folder, so a Files or Changes screenshot
        # shows the real tree and the real diff rather than invented rows.
        # Falls back to a plausible path when the checkout is not to hand.
        checkout = Path(__file__).resolve().parent.parent
        self._working_directory = str(checkout) if (checkout / "pyproject.toml").is_file() \
            else str(Path.home() / "Projects" / "wynxq-gui")
        self._recent_projects = [self._working_directory,
                                 str(Path.home() / "Projects" / "portal-bridge"),
                                 str(Path.home() / "Projects" / "notes")]
        self.dock.set_project(self._working_directory)
        self._task_id = created[0]["id"]
        self._task_title = created[0]["title"]
        self._task_mode = "chat"
        self._task_mode_locked = True
        self._num_ctx = 16384
        self._run_metrics = {"tokens": 427, "prompt_tokens": 1243, "cached_prompt_tokens": 792,
                             "load_ms": 812.0, "total_ms": 7360.0, "tokens_per_second": 18.6}
        self._token_rate = "18.6 tok/s"
        self.store.record_token_usage(self._task_id, "qwen2.5vl:7b", self._run_metrics,
                                      created_at=now - 90)
        if self.scene == "usage":
            for conversation, offset, output, prompt, cached, rate in (
                (created[1], 2 * 3600, 780, 4120, 1200, 18.4),
                (created[2], 2 * 86400, 2320, 11800, 4600, 20.2),
                (created[3], 10 * 86400, 4400, 24500, 9100, 16.8),
                (created[4], 40 * 86400, 9800, 58200, 18000, 14.9),
            ):
                self.store.record_token_usage(
                    conversation["id"], "qwen2.5vl:7b",
                    {"tokens": output, "prompt_tokens": prompt,
                     "cached_prompt_tokens": cached, "load_ms": 0.0,
                     "total_ms": 0.0, "tokens_per_second": rate},
                    created_at=now - offset,
                )
        self._usage.refresh()
        self._conversation_tokens = self._read_conversation_tokens()
        self._usage.exact_metrics(self._run_metrics)
        self.usageChanged.emit()

        if self.scene.startswith("dock-"):
            self._seed_dock_scene(self.scene[len("dock-"):])
            return
        if self.scene == "welcome":
            self._task_id = ""
            self._task_title = "New task"
            self._task_mode = "chat"
            self._task_mode_locked = False
            self._onboarded = False
            self._reset_usage_context()
            self.changed.emit()
            return
        if self.scene.startswith("empty"):
            self._task_id = ""
            self._task_title = "New task"
            if self.scene == "empty-work-locked":
                self._task_mode, self._task_mode_locked = "work", True
            elif self.scene == "empty-chat-locked":
                self._task_mode, self._task_mode_locked = "chat", True
            else:
                self._task_mode, self._task_mode_locked = "chat", False
            self._reset_usage_context()
            self.changed.emit()
            return
        if self.scene.startswith("context"):
            self._task_mode, self._task_mode_locked = "chat", False
            self._seed_context_scene()
            self._reset_usage_context()
            return

        if self.scene == "sent-context":
            self._seed_sent_context_scene()
            return
        if self.scene == "collapsed-shell":
            self._seed_collapsed_shell()
            return
        if self.scene == "thinking":
            self._seed_thinking_scene()
            return
        if self.scene == "work-run":
            self._seed_code_run()
            return
        if self.scene in ("desktop", "run"):
            self._task_mode, self._task_mode_locked = "work", True
            self.store.set_setting(self._mode_key(self._task_id), "work")

        self.messages.append_message("user", "What's on my screen? Can you help me fix it?")
        if self.scene == "desktop":
            self._seed_desktop_scene()
            return
        if self.scene == "run":
            self._seed_finished_run()
            return
        self.messages.append_activity(STEPS[0])
        self.messages.update_last_step(**{k: STEPS[0][k] for k in ("state", "ms", "output")})
        self._seed_answer()
        self.changed.emit()

    def _seed_answer(self):
        row = self.messages.append_message("assistant", streaming=False)
        item = self.messages.items[row]
        item["thought"] = THINKING
        item["thinkSeconds"] = 8.2
        item["thinkDone"] = True
        item["body"] = ANSWER
        item["blocks"] = md.segment(ANSWER)
        self.messages._emit(row, list(Messages_roles()))

    def _seed_sent_context_scene(self):
        """A sent turn with persistent file and image context, for visual QA."""
        self._task_mode, self._task_mode_locked = "chat", True
        self._task_title = "Review attached context"
        self.messages.replace([])
        attached = [
            ctx.from_capture(
                {"ok": True, "image": _SWATCH, "width": 1280, "height": 720},
                ctx.SCREENSHOT, title="screen.png", detail="Full screen",
            ),
            ctx.make(
                ctx.FILE, "Composer.qml",
                path="/home/you/wynxq/ui/Wynxq/Composer.qml",
                text="Item {\n    property bool polished: true\n}\n",
                subtitle="312 lines · 18 KB",
            ),
        ]
        self.messages.append_message(
            "user", "Can you review these and tell me what looks off?",
            attachments=ctx.display_attachments(attached),
        )
        self.messages.append_message(
            "assistant",
            "Yep — I have both the screenshot and Composer.qml. The attachment "
            "context stays with your message, so the conversation reads as one turn "
            "instead of a detached tool event.",
        )
        self.changed.emit()

    def _seed_collapsed_shell(self):
        """Both side surfaces hidden, leaving only the lower restore controls."""
        self._task_mode, self._task_mode_locked = "work", True
        self._sidebar_collapsed = True
        self.dock.setVisible(False)
        self.messages.replace([])
        self.messages.append_message(
            "user", "Keep the workspace out of the way while I read this answer.")
        self.messages.append_message(
            "assistant", "Both side surfaces are fully hidden. The canvas keeps only one "
            "restore control in each lower corner, so there is no leftover icon rail.")
        self.changed.emit()

    def _seed_thinking_scene(self):
        """A deterministic live response for motion/status screenshot QA."""
        self._task_mode, self._task_mode_locked = "work", True
        self.messages.replace([])
        self.messages.append_message("user", "Inspect the project and plan the cleanest fix.")
        self.messages.append_message(
            "assistant", thought="Reading the request and mapping the smallest safe change…",
            streaming=True)
        self._busy = True
        self._status = "Thinking"
        self.changed.emit()

    def _seed_code_run(self):
        """A project-focused Work turn: execution blocks, then the answer."""
        self._task_mode, self._task_mode_locked = "work", True
        self._task_title = "Rewrite the composer layout"
        self.store.set_setting(self._mode_key(self._task_id), "work")
        self.messages.replace([])
        self.messages.append_message(
            "user", "The composer is too tall on a fresh task. Find where the height "
                    "comes from, tighten it, and run the QML tests.")
        for step in CODE_STEPS:
            self.messages.append_activity(step)
            self.messages.update_last_step(**{k: step[k] for k in ("state", "ms", "output")})
            self.dock.record(step)
            self.dock.record_update(**{k: step[k] for k in ("state", "ms", "output")})
        self._activity = [dict(step) for step in CODE_STEPS]
        self.messages.append_message(
            "assistant",
            "The height came from the scroll area's minimum, not from the text: a fresh "
            "task reserved `68px` for a field holding one line.\n\n"
            "`Composer.qml` now asks for **48px** on a fresh task and **38px** in a "
            "conversation, and grows with what you type. The QML asset tests still pass.")
        self._run_metrics = {"tokens": 214, "prompt_tokens": 3810, "cached_prompt_tokens": 2400,
                             "load_ms": 0.0, "total_ms": 9120.0, "tokens_per_second": 23.4}
        self._token_rate = "23.4 tok/s"
        self.activityChanged.emit()
        self.changed.emit()

    def _seed_finished_run(self):
        self._task_title = "Draw a mountain scene in KolourPaint"
        finished = []
        for step in STEPS:
            done = dict(step)
            if done["state"] in ("waiting", "running"):
                done["state"] = "done"
                done["ms"] = 240
            finished.append(done)
        finished[-1]["output"] = "Saved as mountains.png"
        for step in finished:
            self.messages.append_activity(step)
        self._activity = [dict(step) for step in finished]
        self.messages.append_message(
            "assistant",
            "Done. KolourPaint is open with a mountain scene on a 1024 × 768 canvas, saved to **mountains.png** in your pictures folder.\n\n"
            "The ridge line is a single drag through 24 points; the sun is a filled ellipse. Say the word if you want the colours changed.")
        self.activityChanged.emit()
        self.changed.emit()

    def _seed_dock_scene(self, tab: str):
        """A Work conversation with one dock panel open, for the README shots."""
        self._task_mode, self._task_mode_locked = "work", True
        self.store.set_setting(self._mode_key(self._task_id), "work")
        self.messages.append_message("user", "Have a look at the composer and tell me what changed.")
        for step in STEPS[:2]:
            self.messages.append_activity(step)
            self.messages.update_last_step(**{k: step[k] for k in ("state", "ms", "output")})
            self.dock.record(step)
            self.dock.record_update(**{k: step[k] for k in ("state", "ms", "output")})
        self._seed_answer()
        self.dock.setVisible(True)
        self.dock.setTab(tab if tab in ("files", "terminal", "changes", "context",
                                        "memory", "activity", "browser", "preview") else "files")
        if tab == "files":
            target = Path(self._working_directory) / "wynxq" / "ui" / "Wynxq" / "Composer.qml"
            if target.is_file():
                self.dock.openFile(str(target))
                self.dock.revealFile(str(target))
        elif tab == "changes":
            self.dock.refreshChanges()
        elif tab == "context":
            self._attachments = [
                ctx.make(ctx.FILE, "Composer.qml",
                         path=str(Path(self._working_directory) / "wynxq/ui/Wynxq/Composer.qml"),
                         text="Item {\n}\n" * 60, subtitle="403 lines · 14 KB"),
                ctx.from_capture({"ok": True, "image": _SWATCH, "width": 2560, "height": 1440},
                                 ctx.SCREENSHOT, title="Screen", detail="Full screen"),
            ]
            self.attachmentsChanged.emit()
        elif tab == "terminal":
            self.dock.startTerminal()
        elif tab == "browser" and self.dock.browserAvailable:
            self._page_server, url = serve_preview_page()
            self.dock.navigate(url)
        self.activityChanged.emit()
        self.changed.emit()

    def _seed_context_scene(self):
        self._task_id = ""
        self._task_title = "New task"
        self._attachments = [
            ctx.from_capture({"ok": True, "image": _SWATCH, "width": 2560, "height": 1440},
                             ctx.SCREENSHOT, title="Screen", detail="Full screen"),
            ctx.make(ctx.FILE, "controller.py", path="/home/you/wynxq/controller.py",
                     text="class Controller:\n    pass\n" * 40, subtitle="1240 lines · 38 KB"),
            ctx.make(ctx.FOLDER, "wynxq", path="/home/you/wynxq",
                     text="ui/\ncontroller.py\nengine.py", subtitle="12 items"),
        ]
        self.attachmentsChanged.emit()
        self.changed.emit()

    def _seed_desktop_scene(self):
        self._task_title = "Draw a mountain scene in KolourPaint"
        self._busy = True
        self._status = "Type “mountains.png”"
        for step in STEPS:
            self.messages.append_activity(step)
        self._activity = [dict(step) for step in STEPS]
        self._pending_permission = {
            "tool": "type_text", "risk": "sensitive", "summary": "Type “mountains.png”",
            "detail": '{"text": "mountains.png"}',
        }
        self.activityChanged.emit()
        self.permissionChanged.emit()
        self.changed.emit()

    def shutdown(self):
        super().shutdown()
        if self._page_server is not None:
            try:
                self._page_server.shutdown()
                self._page_server.server_close()
            except Exception:
                pass
            self._page_server = None
        try:
            self.store.close()
        except Exception:
            pass


def Messages_roles():
    from .controller import Messages
    return (Messages.BODY, Messages.BLOCKS, Messages.THOUGHT, Messages.ATTACHMENTS,
            Messages.THINK_SECONDS, Messages.THINK_DONE, Messages.STREAMING)


SCENES = [
    ("01-new-task", "empty", ""),
    ("02-task", "conversation", ""),
    ("03-agent-run", "run", ""),
    ("04-permission", "desktop", ""),
    ("05-context", "context", ""),
    ("06-models", "conversation", "modelPicker"),
    ("07-model-manager", "conversation", "models"),
    ("08-settings", "conversation", "settings"),
    ("09-command-palette", "conversation", "palette"),
    ("10-quick-bar", "empty", "quickbar"),
    ("11-welcome", "welcome", "welcome"),
    ("12-appearance", "conversation", "appearanceSettings"),
    ("13-violet-home", "empty-violet", ""),
    ("14-ember-home", "empty-ember", ""),
    ("15-ion-conversation", "conversation-ion", ""),
    ("17-work-home", "empty-work-locked", ""),
    ("18-chat-locked-home", "empty-chat-locked", ""),
    ("19-dock-files", "dock-files", ""),
    ("20-dock-terminal", "dock-terminal", ""),
    ("21-dock-changes", "dock-changes", ""),
    ("22-dock-browser", "dock-browser", ""),
    ("23-dock-context", "dock-context", ""),
    ("24-dock-activity", "dock-activity", ""),
    ("27-dock-memory", "dock-memory", ""),
    ("28-usage", "usage", "usageSettings"),
    ("29-sent-context", "sent-context", ""),
    ("30-collapsed-shell", "collapsed-shell", ""),
    ("31-thinking", "thinking", ""),
    ("25-system", "conversation", "system"),
    ("26-code-run", "work-run", ""),
]
