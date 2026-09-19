"""Real subprocess checks for the local copilot command runner."""
import shlex
import sys
import threading
import time

import pytest

from wynxq.commands import OUTPUT_LIMIT, run_command


def python_command(source):
    return shlex.join([sys.executable, "-c", source])


def test_captures_stdout_stderr_exit_status_and_working_directory(tmp_path):
    result = run_command("printf hello; printf error >&2; pwd; exit 7", str(tmp_path))
    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert "helloerror" in result["output"]
    assert str(tmp_path) in result["output"]


def test_output_is_bounded_without_deadlocking():
    result = run_command(python_command("print('x' * 200000)"))
    assert result["ok"] and result["truncated"]
    assert len(result["output"]) == OUTPUT_LIMIT


def test_timeout_stops_a_command_and_returns_partial_output():
    started = time.monotonic()
    result = run_command("printf started; sleep 20", timeout=1)
    assert "timed out" in result["error"]
    assert result["output"] == "started"
    assert time.monotonic() - started < 3


def test_stop_interrupts_a_command(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    timer.start()
    try:
        result = run_command("sleep 10; touch late", str(tmp_path), cancel=cancel)
        assert "Stopped" in result["error"]
        assert not (tmp_path / "late").exists()
    finally:
        timer.join()


def test_closed_stdout_does_not_hide_a_running_command():
    result = run_command("exec 1>&- 2>&-; sleep 10", timeout=1)
    assert "timed out" in result["error"]


def test_invalid_working_directory_fails_before_execution(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_command("touch unexpected", str(tmp_path / "missing"))
    assert not (tmp_path / "unexpected").exists()
