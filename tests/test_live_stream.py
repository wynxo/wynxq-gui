"""End-to-end: a real Controller streaming from a real local HTTP server.

This exercises the whole path the user sees — worker thread, event bus, message
model, incremental segmentation — rather than any one piece of it.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QCoreApplication

from wynxq.controller import Controller
from wynxq.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])

REPLY = [
    {"message": {"thinking": "The user wants a function. "}, "done": False},
    {"message": {"thinking": "I will keep it short."}, "done": False},
    {"message": {"content": "Here is one.\n\n"}, "done": False},
    {"message": {"content": "```python\ndef add"}, "done": False},
    {"message": {"content": "(a, b):\n    return a + b\n```\n\n"}, "done": False},
    {"message": {"content": "Call it with two numbers."}, "done": True,
     "eval_count": 24, "eval_duration": 1_200_000_000, "prompt_eval_count": 96,
     "prompt_eval_cached_count": 40, "load_duration": 300_000_000,
     "total_duration": 1_600_000_000},
]


class IdleDesktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def disconnect(self):
        return None


@pytest.fixture
def ollama():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({"models": [
                {"name": "local:test", "size": 4_100_000_000,
                 "details": {"family": "test", "parameter_size": "7B", "quantization_level": "Q4_K_M"}},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/show":
                body = json.dumps({"capabilities": ["completion", "thinking"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for chunk in REPLY:
                self.wfile.write(json.dumps(chunk).encode() + b"\n")
                self.wfile.flush()
                time.sleep(0.01)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def pump(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_full_turn_streams_into_the_message_model(ollama, tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("endpoint", ollama)
    store.set_setting("model", "local:test")
    store.set_setting("think", True)
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=True)
    try:
        assert pump(lambda: bridge.online and not bridge.modelCapabilitiesLoading)
        assert bridge.models == ["local:test"]
        assert bridge.modelCatalog[0]["parameters"] == "7B"
        assert bridge.modelSupportsThinking is True

        bridge.send("Write me an add function")
        assert pump(lambda: not bridge.busy)

        kinds = [item["kind"] for item in bridge.messages.items]
        assert kinds == ["user", "assistant"]
        answer = bridge.messages.items[-1]
        assert answer["streaming"] is False
        assert answer["tail"] == ""
        assert answer["thought"].startswith("The user wants a function.")
        assert answer["thinkDone"] is True

        blocks = answer["blocks"]
        assert [block["kind"] for block in blocks] == ["markdown", "code", "markdown"]
        assert blocks[1]["language"] == "python"
        assert blocks[1]["text"] == "def add(a, b):\n    return a + b\n"
        assert blocks[2]["text"] == "Call it with two numbers."

        # Metrics reached the inspector, and history reached disk.
        assert bridge.runMetrics["tokens"] == 24
        assert bridge.runMetrics["cachedTokens"] == 40
        assert bridge.runMetrics["rate"] == 20.0
        assert bridge.taskId
        saved = store.get_messages(bridge.taskId)
        assert saved[0]["content"] == "Write me an add function"
        assert "def add" in saved[1]["content"]
    finally:
        bridge.shutdown()
        store.close()


def test_reopening_the_saved_turn_rebuilds_the_same_blocks(ollama, tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("endpoint", ollama)
    store.set_setting("model", "local:test")
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=True)
    try:
        assert pump(lambda: bridge.online)
        bridge.send("hello")
        assert pump(lambda: not bridge.busy)
        streamed = bridge.messages.items[-1]["blocks"]
        task = bridge.taskId

        bridge.newTask()
        bridge.openTask(task)
        assert bridge.messages.items[-1]["blocks"] == streamed
    finally:
        bridge.shutdown()
        store.close()


def test_stopping_mid_stream_leaves_a_usable_transcript(ollama, tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("endpoint", ollama)
    store.set_setting("model", "local:test")
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=True)
    try:
        assert pump(lambda: bridge.online)
        bridge.send("hello")
        assert pump(lambda: bridge.busy)
        bridge.stop()
        assert pump(lambda: not bridge.busy)
        assert bridge.status in ("Stopped", "Ready when you are")
        # Nothing is left mid-flight in the view.
        assert all(not item["streaming"] for item in bridge.messages.items)
    finally:
        bridge.shutdown()
        store.close()
