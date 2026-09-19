"""Run the actual popup rendering regression in its own GUI process."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

@pytest.mark.skipif(not os.environ.get('WYNXQ_QML_SMOKE'), reason='needs a Qt platform plugin')
def test_popup_pixels_do_not_bleed_through():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('popup_surface_probe.py'))],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'popup surfaces: ok' in result.stdout
    assert 'ReferenceError' not in result.stderr
    assert 'Binding loop' not in result.stderr
