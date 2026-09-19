"""Startup-level regressions for the workspace controller.

These tests stay deliberately tiny: an error in a Qt Property decorator can make
Wynxq die while importing, before the normal GUI smoke test even creates a
window. Keep an explicit import guard so that class-definition failures are
reported immediately.
"""
from pathlib import Path


def test_workspace_controller_imports_cleanly():
    import wynxq.workspace as workspace

    assert workspace.WorkspaceController.__name__ == "WorkspaceController"


def test_workspace_properties_use_subclass_owned_notify_signals():
    import wynxq.workspace as workspace

    source = Path(workspace.__file__).read_text(encoding="utf-8")
    assert "notify=changed" not in source
    assert "notify=Controller.changed" not in source
    assert "contextStateChanged = Signal()" in source
    assert "notify=contextStateChanged" in source
