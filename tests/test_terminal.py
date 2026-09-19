"""The PTY-backed shell and the ANSI screen behind the Terminal panel.

These run a real shell. They are the difference between "the panel looks like a
terminal" and "the panel is one": `cd` has to persist, Ctrl+C has to reach the
foreground process, and colour has to survive.
"""
import os
import time

import pytest

from wynxq.terminal import AnsiScreen, ShellSession


# ------------------------------------------------------------- the ANSI screen
def test_plain_text_becomes_one_row_per_line():
    screen = AnsiScreen()
    screen.feed("first\nsecond\n")
    assert [row["text"] for row in screen.rows()] == ["first", "second"]


def test_colour_is_kept_as_a_span_rather_than_stripped():
    screen = AnsiScreen()
    screen.feed("ok \x1b[31mFAILED\x1b[0m done\n")
    spans = screen.rows()[0]["spans"]
    assert "".join(span["text"] for span in spans) == "ok FAILED done"
    assert any(span["fg"] == "red" and span["text"] == "FAILED" for span in spans)


def test_bold_and_bright_are_recorded():
    screen = AnsiScreen()
    screen.feed("\x1b[1;32mpass\x1b[0m\n")
    span = screen.rows()[0]["spans"][0]
    assert span["bold"] is True and span["fg"] == "green"


def test_truecolour_collapses_onto_a_named_slot():
    screen = AnsiScreen()
    screen.feed("\x1b[38;2;220;40;40mred-ish\x1b[0m\n")
    assert screen.rows()[0]["spans"][0]["fg"] in ("red", "brightRed")


def test_carriage_return_overwrites_the_line_a_progress_bar_redraws():
    screen = AnsiScreen()
    screen.feed("50%\r100%\n")
    assert [row["text"] for row in screen.rows()] == ["100%"]


def test_erase_in_line_clears_the_rest_of_the_row():
    screen = AnsiScreen()
    screen.feed("abcdef\r\x1b[Kxy\n")
    assert screen.rows()[0]["text"] == "xy"


def test_clearing_the_display_empties_the_scrollback():
    screen = AnsiScreen()
    screen.feed("noise\n\x1b[2Jfresh\n")
    assert [row["text"] for row in screen.rows()] == ["fresh"]


def test_the_scrollback_is_bounded():
    screen = AnsiScreen(max_lines=10)
    screen.feed("".join(f"line {n}\n" for n in range(200)))
    rows = screen.rows()
    assert len(rows) <= 10
    assert rows[-1]["text"] == "line 199"


def test_an_over_long_line_is_cut_rather_than_grown_without_end():
    screen = AnsiScreen()
    screen.feed("x" * 20000 + "\n")
    assert len(screen.rows()[0]["text"]) <= 4000


def test_osc_titles_and_stray_escapes_do_not_reach_the_output():
    screen = AnsiScreen()
    screen.feed("\x1b]0;a window title\x07visible\n")
    assert screen.rows()[0]["text"] == "visible"


# ------------------------------------------------------------- the real shell
@pytest.fixture
def shell(tmp_path):
    session = ShellSession(cwd=str(tmp_path), shell="/bin/bash")
    session.start()
    yield session
    session.stop()


def drain(session, needle, timeout=8.0):
    """Read until the scrollback contains `needle`, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.read()
        if needle in session.screen.plain_text():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_a_session_starts_and_runs_a_command(shell):
    # Split in the source so the terminal's echo of the command line cannot be
    # mistaken for the command having actually run.
    shell.send_line('echo "WYNXQ""_MARKER"')
    assert drain(shell, "WYNXQ_MARKER")
    assert shell.running


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_the_working_directory_persists_across_commands(shell, tmp_path):
    """The whole reason this is a PTY and not `subprocess.run` per command."""
    (tmp_path / "sub").mkdir()
    shell.send_line("cd sub")
    # Poll the shell's real directory rather than its echo of the command.
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        shell.read()
        if shell.working_directory().endswith("sub"):
            break
        time.sleep(0.05)
    assert shell.working_directory().endswith("sub")

    shell.send_line('echo "MOVED""_HERE"')
    assert drain(shell, "MOVED_HERE")


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_the_shell_reports_its_name(shell):
    assert shell.shell_name == "bash"


def foreground_is_a_child(session, timeout=8.0):
    """Wait until the command — not the shell — owns the terminal.

    Interrupting before that point signals the shell itself, which is what a
    real Ctrl+C at an empty prompt does, and would make this test a coin flip.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.read()
        try:
            if os.tcgetpgrp(session.fd) != session.pid:
                return True
        except OSError:
            return False
        time.sleep(0.02)
    return False


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_interrupt_stops_a_running_command(shell):
    # The marker is split in the source so the terminal's echo of the command
    # line cannot be mistaken for the command having produced output.
    shell.send_line('sleep 30; echo "AFTER""_SLEEP"')
    assert foreground_is_a_child(shell), "sleep never took the terminal"
    shell.interrupt()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        shell.read()
        time.sleep(0.05)
    assert "AFTER_SLEEP" not in shell.screen.plain_text()
    assert shell.running                       # the shell survives its child


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_interrupting_at_an_empty_prompt_leaves_the_shell_alone(shell):
    """The same gesture a terminal makes: a fresh prompt, not a dead shell."""
    assert drain(shell, "$", timeout=5) or shell.running
    shell.interrupt()
    time.sleep(0.4)
    shell.read()
    assert shell.running
    shell.send_line("echo STILL_HERE")
    assert drain(shell, "STILL_HERE")


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_stopping_ends_the_session(shell):
    shell.stop()
    assert not shell.running
    assert shell.fd == -1


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_reading_an_idle_shell_returns_nothing_rather_than_blocking(shell):
    drain(shell, "$", timeout=3)
    start = time.monotonic()
    shell.read()
    assert time.monotonic() - start < 1.0


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="needs bash")
def test_writing_to_a_stopped_session_is_a_no_op(shell):
    shell.stop()
    shell.send_line("echo nope")           # must not raise
    assert not shell.running
