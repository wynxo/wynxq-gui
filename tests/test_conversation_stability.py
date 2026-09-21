"""Regression checks for pointer-induced jumps and inaccessible controls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("WYNXQ_QML_SMOKE"),
                                reason="needs a Qt platform plugin")


@pytest.fixture(scope="module")
def measured():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("conversation_stability_probe.py"))],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ReferenceError" not in result.stderr, result.stderr
    assert "Binding loop" not in result.stderr, result.stderr
    assert "TypeError" not in result.stderr, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_hover_does_not_resize_an_older_answer(measured):
    assert measured["answer_hover_height_delta"] == 0


def test_keyboard_can_reveal_actions_and_copy_an_older_answer(measured):
    assert measured["keyboard_actions_visible"]
    assert measured["keyboard_actions_height_delta"] == 0
    assert measured["keyboard_copied_answer"]


def test_short_answer_actions_stay_directly_below_the_text(measured):
    # Theme.s2 is 8 px; allow one extra spacing unit for platform rounding.
    assert 0 <= measured["short_answer_action_gap"] <= 16, measured
    assert measured["short_answer_actions_offset"] < 96, measured
    assert measured["short_answer_height"] < 128, measured


def test_following_survives_a_shrinking_viewport(measured):
    assert measured["initial_at_bottom"], measured["initial_geometry"]
    assert measured["resize_at_bottom"], measured["resized_geometry"]


def test_dragging_the_scrollbar_pauses_following(measured):
    assert measured["scrollbar_left_bottom"]
    assert measured["scrollbar_paused_following"]
    # Qt can round the thumb's fractional contentY to a device pixel.
    assert measured["append_while_reading_y_delta"] <= 1
    assert measured["jump_resumes_following"]


def test_recycled_messages_do_not_inherit_an_open_editor(measured):
    assert measured["edited_row_was_scrolled_away"]
    assert measured["recycled_editor_closed"]


def test_long_permission_stays_scrollable_with_reachable_decisions(measured):
    assert measured["permission_height"] < measured["window_height"]
    assert measured["permission_details_height"] < measured["window_height"]
    assert measured["permission_actions_inside"]
    assert measured["permission_no_overlap"]
    assert measured["permission_scrollable"]
    assert measured["permission_defaults_to_deny"]


def test_long_draft_with_twelve_attachments_keeps_send_in_the_window(measured):
    assert measured["long_draft_send_inside"], measured["long_draft_composer_height"]
    assert measured["long_draft_preserved"]
    assert measured["attachments_scrollable"]
    assert measured["long_draft_starters_inside"], measured["long_draft_geometry"]
