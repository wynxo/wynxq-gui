"""The workspace dock: its state rules, its browser policy, its timeline.

The two behaviours worth defending here are the ones a user notices: the dock
never moves the panel they chose, and it remembers where they left it.
"""
import pytest

from wynxq import activity, browser


# ------------------------------------------------------------ browser policy
@pytest.mark.parametrize("typed, expected", [
    ("example.com", "https://example.com"),
    ("https://example.com/a?b=c", "https://example.com/a?b=c"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("localhost:8080/x", "http://localhost:8080/x"),
    ("127.0.0.1:3000", "http://127.0.0.1:3000"),
    ("[::1]:5173/app", "http://[::1]:5173/app"),
    ("192.168.1.5", "https://192.168.1.5"),
])
def test_an_address_is_taken_as_an_address(typed, expected):
    assert browser.normalize(typed) == expected


@pytest.mark.parametrize("typed", [
    "fix the login bug",
    "what is a monad",
    "wynxq redesign",
])
def test_a_phrase_becomes_a_search(typed):
    result = browser.normalize(typed)
    assert result.startswith(browser.SEARCH_TEMPLATE.split("{")[0])


@pytest.mark.parametrize("typed", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "data:text/html,<script>x</script>",
    "chrome://settings",
    "about:config",
    "",
    "   ",
    "http://exa\nmple.com",
    "example.com:not-a-port",
])
def test_a_scheme_the_panel_will_not_open_is_refused_outright(typed):
    """Refused, not rewritten: the address bar must never lie about where you
    are, and a `file://` URL is not something a web panel should follow."""
    assert browser.normalize(typed) == ""


def test_the_address_bar_reads_a_url_without_its_noise():
    assert browser.display_url("https://example.com/docs/") == "example.com/docs"
    assert browser.display_url("https://example.com") == "example.com"
    assert browser.display_url("about:blank") == ""
    assert browser.display_url("") == ""


def test_loopback_is_local_rather_than_insecure():
    """A warning triangle on your own dev server is a warning people learn to
    ignore, so loopback gets a neutral mark instead."""
    assert browser.is_local("http://127.0.0.1:8000/") is True
    assert browser.is_local("http://localhost:3000") is True
    assert browser.is_local("http://[::1]:5173") is True
    assert browser.is_local("http://example.com") is False
    assert browser.is_secure("https://example.com") is True
    assert browser.is_secure("http://example.com") is False


def test_a_page_handed_over_is_bounded_and_labelled():
    page = browser.page_context("https://example.com/x", "Title", "y" * 200000)
    assert page["truncated"] is True
    assert len(page["text"]) == browser.MAX_PAGE_TEXT
    assert page["host"] == "example.com"
    assert page["secure"] is True


def test_a_page_with_no_title_falls_back_to_its_address():
    assert browser.page_context("https://example.com/x", "", "body")["title"] == "example.com/x"


# ------------------------------------------------------------- the timeline
def test_states_the_engine_reports_are_normalised_to_the_panel_vocabulary():
    assert activity.normalise_state("declined") == activity.CANCELLED
    assert activity.normalise_state("error") == activity.FAILED
    assert activity.normalise_state("ok") == activity.DONE
    assert activity.normalise_state("nonsense") == activity.QUEUED
    assert activity.normalise_state(None) == activity.QUEUED


def test_a_step_can_be_settled_after_it_is_announced():
    log = activity.ActivityLog()
    log.begin_turn("Fix the tests")
    log.append({"kind": "step", "label": "Run tests", "state": "running"})
    log.update_last(state="done", ms=1420, output="46 passed")

    step = [event for event in log.rows() if event["kind"] == "step"][-1]
    assert step["state"] == "done"
    assert step["durationLabel"] == "1.4s"
    assert step["output"] == "46 passed"


def test_settling_a_turn_closes_anything_still_open():
    log = activity.ActivityLog()
    log.begin_turn("Turn")
    log.append({"kind": "step", "label": "One", "state": "done"})
    log.append({"kind": "step", "label": "Two", "state": "running"})
    log.settle_turn("cancelled")

    states = [event["state"] for event in log.rows() if event["kind"] == "step"]
    assert states == ["done", "cancelled"]
    assert log.running is False


def test_the_summary_counts_what_went_wrong():
    log = activity.ActivityLog()
    log.append({"kind": "step", "label": "a", "state": "done", "ms": 500})
    log.append({"kind": "step", "label": "b", "state": "failed", "ms": 200})
    summary = log.summary()
    assert "2 steps" in summary and "1 failed" in summary


def test_the_timeline_is_bounded():
    log = activity.ActivityLog(max_events=10)
    for index in range(100):
        log.append({"kind": "step", "label": str(index), "state": "done"})
    assert len(log.rows()) == 10
    assert log.rows()[-1]["label"] == "99"


def test_output_on_an_event_is_capped():
    log = activity.ActivityLog()
    log.append({"kind": "step", "label": "noisy", "state": "done", "output": "x" * 99999})
    assert len(log.rows()[0]["output"]) == activity.MAX_OUTPUT


def test_durations_read_the_way_a_person_would_say_them():
    assert activity.format_duration(0) == ""
    assert activity.format_duration(412) == "412ms"
    assert activity.format_duration(1420) == "1.4s"
    assert activity.format_duration(95000) == "1m 35s"