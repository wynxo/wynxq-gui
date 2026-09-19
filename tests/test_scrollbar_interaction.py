"""Check scrollbars through real pointer events in the application."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('WYNXQ_QML_SMOKE'), reason='needs a Qt platform plugin')
def test_scrollbar_hover_drag_and_idle():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('scrollbar_probe.py'))],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for warning in ('ReferenceError', 'Binding loop', 'TypeError'):
        assert warning not in result.stderr, result.stderr
