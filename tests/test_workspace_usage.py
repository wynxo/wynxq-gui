"""The actual QML bridge must expose the live counter and exact reconciliation."""
from PySide6.QtCore import QCoreApplication

from wynxo.storage import Store
from wynxo.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


class Desktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "off"}

    def disconnect(self):
        return None

    def active_window(self):
        return {"title": "", "detail": ""}


def test_workspace_exposes_estimated_then_exact_live_tokens(tmp_path):
    bridge = WorkspaceController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=Desktop(),
        autoconnect=False,
    )

    bridge._on_event({"type": "token", "text": "A visible answer begins with several words. "})
    estimate = bridge.liveOutputTokens
    assert estimate > 0

    bridge._on_event({
        "type": "metrics",
        "tokens": 45,
        "prompt_tokens": 120,
        "cached_prompt_tokens": 20,
        "load_ms": 80.0,
        "total_ms": 18000.0,
        "tokens_per_second": 2.5,
    })

    assert bridge.liveOutputTokens == 45
    assert bridge.liveTokenRate == 2.5
    bridge.shutdown()
    bridge.store.close()


def test_workspace_period_summary_refreshes_after_exact_run(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    bridge = WorkspaceController(store=store, desktop=Desktop(), autoconnect=False)
    bridge._task_id = "usage-test"
    bridge._model = "test-model"

    bridge._usage.exact_metrics({
        "tokens": 40,
        "prompt_tokens": 60,
        "cached_prompt_tokens": 10,
        "tokens_per_second": 5.0,
    })
    assert bridge._usage.finalize(bridge._task_id, bridge._model)

    assert bridge.tokenUsage["today"]["tokens"] == 100
    assert bridge.tokenUsage["week"]["tokens"] == 100
    assert bridge.tokenUsage["month"]["tokens"] == 100
    assert bridge.tokenUsage["allTime"]["tokens"] == 100
    bridge.shutdown()
    store.close()


def test_current_chat_usage_is_cached_and_switching_clears_stale_live_speed(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    first = store.create_conversation("first", "model")
    second = store.create_conversation("second", "model")
    store.record_token_usage(first["id"], "model", {
        "tokens": 10, "prompt_tokens": 90, "cached_prompt_tokens": 70,
        "tokens_per_second": 5.0,
    })
    bridge = WorkspaceController(store=store, desktop=Desktop(), autoconnect=False)

    bridge.openTask(first["id"])
    assert bridge.conversationTokens == 100
    bridge._usage.exact_metrics({
        "tokens": 7, "prompt_tokens": 13, "cached_prompt_tokens": 9,
        "tokens_per_second": 3.5,
    })
    bridge.usageChanged.emit()
    assert bridge.liveTokenRate == 3.5
    assert bridge.liveTokenRateExact is True

    bridge.openTask(second["id"])
    assert bridge.conversationTokens == 0
    assert bridge.liveOutputTokens == 0
    assert bridge.liveTokenRate == 0
    assert bridge.liveTokenRateExact is False
    bridge.shutdown()
    store.close()


def test_completed_run_updates_current_chat_total_once(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    task = store.create_conversation("usage", "model")
    bridge = WorkspaceController(store=store, desktop=Desktop(), autoconnect=False)
    bridge.openTask(task["id"])
    bridge._model = "model"
    bridge._usage.exact_metrics({
        "tokens": 11, "prompt_tokens": 29, "cached_prompt_tokens": 20,
        "tokens_per_second": 4.0,
    })

    assert bridge._finalize_usage() is True
    assert bridge.conversationTokens == 40
    assert bridge._finalize_usage() is False
    assert bridge.conversationTokens == 40
    assert store.conversation_token_usage(task["id"])["tokens"] == 40
    bridge.shutdown()
    store.close()
