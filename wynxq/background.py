"""Small concurrency primitives shared by workspace background jobs.

Qt owns the GUI thread, but Python/subprocess work must not run *inside* a
PySide ``QThread``. On Linux, Shiboken can crash the interpreter while a Qt
thread is executing normal Python filesystem/subprocess internals. The dock may
still use Qt to schedule and deliver results, but the expensive body is always
moved onto a standard ``threading.Thread`` first.

Workspace scans and Git reads are also serialized. Running both at once buys us
nothing useful, thrashes the same project tree, and makes stale-result handling
harder to reason about.
"""
from __future__ import annotations

from functools import wraps
import threading

_WORKER_IO_LOCK = threading.RLock()


class _Outcome:
    __slots__ = ("value", "error")

    def __init__(self) -> None:
        self.value = None
        self.error: BaseException | None = None


def _run_in_python_thread(function, args, kwargs):
    """Execute one callable on a real Python-managed thread and re-raise errors."""
    outcome = _Outcome()

    def invoke() -> None:
        try:
            with _WORKER_IO_LOCK:
                outcome.value = function(*args, **kwargs)
        except BaseException as exc:  # preserve the original exception type/traceback
            outcome.error = exc

    worker = threading.Thread(
        target=invoke,
        name=f"wynxq-io:{getattr(function, '__name__', 'job')}",
        daemon=True,
    )
    worker.start()
    worker.join()
    if outcome.error is not None:
        raise outcome.error
    return outcome.value


def serialized_io(function):
    """Run one workspace I/O body at a time on a Python-managed thread.

    The wrapper is intentionally synchronous to its caller. DockController is
    already responsible for keeping that caller off the GUI thread; this extra
    hop exists only to keep ordinary Python/native/subprocess code out of a
    PySide QThread. Direct callers and tests get the same return/exception
    contract as a normal function call.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        return _run_in_python_thread(function, args, kwargs)
    return wrapped


__all__ = ['serialized_io']
