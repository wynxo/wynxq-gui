"""Small concurrency primitives shared by workspace background jobs.

PySide QThreads keep expensive work off the GUI thread, but native directory
scans and subprocess-backed Git work must not execute at the same time. On
Linux, overlapping those jobs can crash inside Qt/Python rather than raising a
recoverable exception. Serializing the expensive bodies keeps the interface
responsive while making their execution deterministic.
"""
from __future__ import annotations

from functools import wraps
import threading

_WORKER_IO_LOCK = threading.RLock()


def serialized_io(function):
    """Run one workspace I/O job body at a time, without blocking the GUI."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _WORKER_IO_LOCK:
            return function(*args, **kwargs)
    return wrapped
