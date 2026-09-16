"""Workspace I/O runs outside PySide-owned worker threads."""
from __future__ import annotations

import threading
import time

import pytest

from wynxo.background import serialized_io


def test_serialized_io_moves_the_body_to_a_python_managed_thread():
    caller = threading.current_thread()

    @serialized_io
    def where():
        return threading.current_thread()

    worker = where()
    assert worker is not caller
    assert worker.name.startswith("wynxo-io:")
    assert type(worker).__name__ != "_DummyThread"


def test_serialized_io_propagates_the_original_exception():
    @serialized_io
    def fail():
        raise ValueError("broken workspace read")

    with pytest.raises(ValueError, match="broken workspace read"):
        fail()


def test_serialized_io_allows_only_one_expensive_body_at_a_time():
    state_lock = threading.Lock()
    active = 0
    peak = 0

    @serialized_io
    def work():
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with state_lock:
            active -= 1

    callers = [threading.Thread(target=work) for _ in range(3)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join()

    assert peak == 1
