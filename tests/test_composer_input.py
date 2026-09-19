"""The real composer must send on Return under Qt, not just look right in QML."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("WYNXQ_QML_SMOKE"),
    reason="needs a Qt platform plugin",
)


@pytest.fixture(scope="module")
def measured():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("composer_input_probe.py"))],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert "ReferenceError" not in result.stderr, result.stderr
    assert "Binding loop" not in result.stderr, result.stderr
    assert "TypeError" not in result.stderr, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_return_really_sends_from_the_text_area(measured):
    assert measured["return_sent"]
    assert measured["return_cleared"]


def test_shift_return_remains_a_newline(measured):
    assert measured["shift_return_did_not_send"]
    assert measured["shift_return_inserted_newline"]
