"""Token counters must feel live without corrupting exact historical totals."""
from datetime import datetime

from wynxo.storage import Store
from wynxo.usage import TokenUsageTracker


def metrics(tokens, prompt, rate=2.5, cached=0, total_ms=1000):
    return {
        "tokens": tokens,
        "prompt_tokens": prompt,
        "cached_prompt_tokens": cached,
        "load_ms": 20,
        "total_ms": total_ms,
        "tokens_per_second": rate,
    }


def test_streamed_estimate_moves_then_exact_metrics_reconcile(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    now = [100.0]
    tracker = TokenUsageTracker(store, clock=lambda: now[0])

    tracker.stream("A short streamed answer starts here. ")
    first = tracker.live_output_tokens
    assert first > 0

    now[0] += 1.0
    tracker.stream("Then several more words arrive from the model in another chunk.")
    assert tracker.live_output_tokens > first
    assert tracker.live_rate > 0

    tracker.exact_metrics(metrics(45, 120, rate=2.5))
    assert tracker.live_output_tokens == 45
    assert tracker.live_rate == 2.5
    assert tracker.metrics["tokens"] == 45
    assert tracker.metrics["prompt_tokens"] == 120
    store.close()


def test_multiple_model_passes_accumulate_exact_usage(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    tracker = TokenUsageTracker(store)

    tracker.exact_metrics(metrics(40, 100, rate=2.0, cached=25))
    tracker.exact_metrics(metrics(5, 60, rate=6.0, cached=10))

    assert tracker.live_output_tokens == 45
    assert tracker.metrics["tokens"] == 45
    assert tracker.metrics["prompt_tokens"] == 160
    assert tracker.metrics["cached_prompt_tokens"] == 35
    # Weighted by generated tokens rather than averaging a 40-token pass and a
    # tiny 5-token pass as if they represented the same amount of work.
    assert round(tracker.metrics["tokens_per_second"], 2) == 2.44
    store.close()


def test_period_buckets_use_local_day_week_month_and_lifetime(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    noon = datetime(2026, 9, 9, 12, 0, 0).timestamp()  # Wednesday

    store.record_token_usage("today", "model", metrics(10, 90),
                             datetime(2026, 9, 9, 8, 0, 0).timestamp())
    store.record_token_usage("week", "model", metrics(20, 80),
                             datetime(2026, 9, 7, 8, 0, 0).timestamp())
    store.record_token_usage("month", "model", metrics(30, 70),
                             datetime(2026, 9, 1, 8, 0, 0).timestamp())
    store.record_token_usage("older", "model", metrics(40, 60),
                             datetime(2026, 8, 31, 8, 0, 0).timestamp())

    summary = store.token_usage_summary(now=noon)
    assert summary["today"]["tokens"] == 100
    assert summary["today"]["runs"] == 1
    assert summary["week"]["tokens"] == 200
    assert summary["week"]["runs"] == 2
    assert summary["month"]["tokens"] == 300
    assert summary["month"]["runs"] == 3
    assert summary["allTime"]["tokens"] == 400
    assert summary["allTime"]["runs"] == 4
    store.close()


def test_period_speed_is_weighted_by_generated_tokens(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    now = datetime(2026, 9, 9, 12, 0, 0).timestamp()

    # The tiny fast response must not count as much as the thousand-token run.
    store.record_token_usage("large", "model", metrics(1000, 100, rate=10.0),
                             created_at=now - 120)
    store.record_token_usage("tiny", "model", metrics(10, 10, rate=100.0),
                             created_at=now - 60)

    summary = store.token_usage_summary(now=now)
    expected = round((1000 * 10.0 + 10 * 100.0) / 1010, 1)
    assert expected == 10.9
    assert summary["today"]["averageRate"] == expected
    assert summary["allTime"]["averageRate"] == expected
    store.close()


def test_all_time_does_not_include_usage_from_the_future(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    now = datetime(2026, 9, 9, 12, 0, 0).timestamp()
    store.record_token_usage("past", "model", metrics(10, 10), created_at=now - 60)
    store.record_token_usage("future", "model", metrics(900, 100), created_at=now + 60)

    summary = store.token_usage_summary(now=now)
    assert summary["allTime"]["tokens"] == 20
    assert summary["allTime"]["runs"] == 1
    store.close()


def test_finalize_persists_only_exact_metrics_once(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    tracker = TokenUsageTracker(store, clock=lambda: 100.0)

    # A live estimate is useful to animate but must never become accounting.
    tracker.stream("This provisional answer is deliberately much longer than one token.")
    provisional = tracker.live_output_tokens
    assert provisional > 0

    tracker.exact_metrics(metrics(7, 13, rate=3.5))
    assert tracker.finalize("chat-id", "test-model") is True
    assert tracker.finalize("chat-id", "test-model") is False

    all_time = tracker.summary["allTime"]
    assert all_time["outputTokens"] == 7
    assert all_time["promptTokens"] == 13
    assert all_time["tokens"] == 20
    assert all_time["runs"] == 1
    store.close()


def test_usage_survives_conversation_deletion(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    conversation = store.create_conversation("temporary", "model")
    store.record_token_usage(conversation["id"], "model", metrics(5, 15))
    store.delete_conversation(conversation["id"])

    assert store.get_conversation(conversation["id"]) is None
    assert store.token_usage_summary()["allTime"]["tokens"] == 20
    store.close()


def test_minimal_store_keeps_live_usage_without_requiring_persistence():
    class MinimalStore:
        pass

    tracker = TokenUsageTracker(MinimalStore(), clock=lambda: 10.0)
    tracker.stream("This still gets a live counter without a database ledger.")
    assert tracker.live_output_tokens > 0
    assert tracker.summary["allTime"]["tokens"] == 0
    tracker.exact_metrics(metrics(9, 11, rate=3.0))
    assert tracker.live_output_tokens == 9
    assert tracker.finalize("", "") is False


def test_live_rate_marks_stream_estimates_and_exact_ollama_metrics(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    now = [10.0]
    tracker = TokenUsageTracker(store, clock=lambda: now[0])
    tracker.stream("first chunk")
    now[0] += 1.0
    tracker.stream(" second chunk with enough text to measure")
    assert tracker.live_rate > 0
    assert tracker.live_rate_exact is False

    tracker.exact_metrics(metrics(12, 34, rate=6.25))
    assert tracker.live_rate == 6.25
    assert tracker.live_rate_exact is True

    now[0] += 1.0
    tracker.stream("new pass")
    assert tracker.live_rate == 0
    assert tracker.live_rate_exact is False
    store.close()


def test_conversation_usage_counts_prompt_plus_output_once(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.record_token_usage("chat-a", "model", metrics(10, 90, cached=70))
    store.record_token_usage("chat-a", "model", metrics(5, 15, cached=10))
    store.record_token_usage("chat-b", "model", metrics(999, 999, cached=999))

    chat = store.conversation_token_usage("chat-a")
    assert chat["outputTokens"] == 15
    assert chat["promptTokens"] == 105
    assert chat["cachedTokens"] == 80
    assert chat["tokens"] == 120
    assert chat["runs"] == 2
    assert store.conversation_token_usage("")["tokens"] == 0
    store.close()


def test_daily_trend_fills_empty_days_and_model_breakdown(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    now = datetime(2026, 9, 9, 12, 0, 0).timestamp()

    store.record_token_usage("a", "qwen", metrics(10, 90, rate=5.0),
                             created_at=datetime(2026, 9, 9, 8, 0, 0).timestamp())
    store.record_token_usage("b", "qwen", metrics(20, 80, rate=10.0),
                             created_at=datetime(2026, 9, 7, 8, 0, 0).timestamp())
    store.record_token_usage("c", "llama", metrics(5, 45, rate=20.0),
                             created_at=datetime(2026, 9, 8, 8, 0, 0).timestamp())

    days = store.token_usage_daily(days=4, now=now)
    assert len(days) == 4
    assert [day["date"] for day in days] == [
        "2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09"
    ]
    assert [day["tokens"] for day in days] == [0, 100, 50, 100]

    models = store.token_usage_models(days=30, now=now)
    assert [model["name"] for model in models] == ["qwen", "llama"]
    assert models[0]["tokens"] == 200
    assert models[0]["runs"] == 2
    assert models[1]["tokens"] == 50
    store.close()


def test_tracker_refreshes_daily_and_model_views(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    tracker = TokenUsageTracker(store)
    tracker.exact_metrics(metrics(10, 20, rate=4.0))
    assert tracker.finalize("chat", "qwen") is True
    assert len(tracker.daily) == 7
    assert tracker.daily[-1]["tokens"] >= 30
    assert tracker.models[0]["name"] == "qwen"
    assert tracker.models[0]["tokens"] >= 30
    store.close()
