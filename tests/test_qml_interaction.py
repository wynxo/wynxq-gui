"""Interaction, not source text: real components, driven and measured.

`qml_probe.py` instantiates the components in a Qt GUI process and reports what
they did. These assertions cover the reliability problems the redesign set out
to remove — surfaces that creep, controls that fight their own bindings, and
text that overflows what is meant to contain it.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PROBE = Path(__file__).resolve().parent / "qml_probe.py"

pytestmark = pytest.mark.skipif(not os.environ.get("WYNXQ_QML_SMOKE"),
                                reason="needs a Qt platform plugin")


@pytest.fixture(scope="module")
def measured():
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
    result = subprocess.run([sys.executable, str(PROBE)], capture_output=True,
                            text=True, timeout=120, env=environment)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert "error" not in report, report["error"]
    return report


def test_a_menu_opens_in_the_same_place_every_time(measured):
    """Adjusting a bound `x` in place made a popover creep a little further
    off-screen on each open. Placement is derived from `anchorX` instead."""
    positions = measured["menu_x_positions"]
    assert len(set(positions)) == 1, f"the menu drifted: {positions}"


def test_a_menu_near_the_window_edge_stays_inside_it(measured):
    assert measured["menu_right_edge"] <= measured["window_width"]


def test_arrow_keys_skip_separators_and_disabled_entries(measured):
    # "three" is disabled and sits behind a separator, so stepping goes
    # one → two → four, then stops rather than wrapping past the end.
    assert measured["menu_walk"] == ["one", "two", "four", "four"]


def test_a_switch_asks_rather_than_flipping_itself(measured):
    """Every switch is bound to a setting. If it toggled itself it would
    overwrite that binding, and a value the controller refused would be shown
    wrongly from then on."""
    assert measured["toggle_requested"] == ["on"]
    assert measured["toggle_checked_after_click"] is False
    assert measured["toggle_follows_binding"] is True


def test_a_constrained_chip_elides_instead_of_overflowing(measured):
    """An attachment name can be far wider than the room it is given."""
    assert measured["chip_implicit_width"] > measured["chip_width"]
    assert measured["chip_content_width"] <= measured["chip_width"]


def test_long_messages_leave_room_for_accessible_actions(measured):
    assert measured["message_height"] > 100
    assert measured["message_actions_left"] >= 0
    assert measured["message_actions_visible"] is True


def test_shell_has_one_sidebar_toggle_and_no_composer_overlap():
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
    result = subprocess.run([sys.executable, str(PROBE.with_name("shell_probe.py"))],
                            capture_output=True, text=True, timeout=30, env=environment)
    assert result.returncode == 0, result.stderr
    assert "ReferenceError" not in result.stderr, result.stderr
    assert "Binding loop" not in result.stderr, result.stderr
    states = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(states) == 6
    for state in states:
        assert state["toggles"] == 1, state
        assert state["composer_inside"], state
        assert state["no_overlap"], state
