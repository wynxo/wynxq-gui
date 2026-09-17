"""The welcome flow remains navigable with long text and no project folder."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('WYNXO_QML_SMOKE'), reason='needs a Qt platform plugin')
def test_welcome_navigation_and_constrained_layout():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('welcome_probe.py'))],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'welcome interactions: ok' in result.stdout
    for warning in ('ReferenceError', 'Binding loop', 'TypeError'):
        assert warning not in result.stderr, result.stderr
