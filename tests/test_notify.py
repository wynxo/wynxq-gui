"""Notification policy. No test here posts a real desktop notification."""
from unittest.mock import patch

from wynxq import notify


def test_only_long_unattended_runs_are_worth_a_notification():
    assert notify.should_notify(30, focused=False, enabled=True) is True
    assert notify.should_notify(30, focused=True, enabled=True) is False
    assert notify.should_notify(2, focused=False, enabled=True) is False
    assert notify.should_notify(30, focused=False, enabled=False) is False


def test_send_is_a_no_op_without_notify_send():
    with patch("shutil.which", return_value=None):
        assert notify.send("Title", "Body") is False
        assert notify.available() is False


def test_send_passes_the_app_identity_and_clamps_long_text():
    with patch("shutil.which", return_value="/usr/bin/notify-send"), \
         patch("subprocess.run") as run:
        run.return_value.returncode = 0
        assert notify.send("Title", "B" * 900, urgency="bogus") is True
    command = run.call_args[0][0]
    assert "--app-name=Wynxq" in command
    assert "--urgency=normal" in command
    assert len(command[-1]) <= 400


def test_open_terminal_tries_known_emulators_then_gives_up():
    with patch("shutil.which", return_value=None):
        assert notify.open_terminal("/tmp") is False
        assert notify.open_path("/tmp") is False


def test_open_path_needs_a_target():
    with patch("shutil.which", return_value="/usr/bin/xdg-open"):
        assert notify.open_path("") is False
