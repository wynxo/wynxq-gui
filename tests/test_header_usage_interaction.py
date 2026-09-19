"""Exercise the actual header, composer summary and Settings usage page."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

@pytest.mark.skipif(not os.environ.get('WYNXQ_QML_SMOKE'), reason='needs a Qt platform plugin')
def test_header_spacing_and_usage_settings():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('header_usage_probe.py'))],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'header and usage interactions: ok' in result.stdout
    for warning in ('ReferenceError', 'Binding loop', 'TypeError'):
        assert warning not in result.stderr, result.stderr
