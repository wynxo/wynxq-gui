"""Safe per-run workspace checkpoints preserve pre-existing user work."""
from pathlib import Path
import subprocess

import pytest

from wynxo.workspace import (
    _checkpoint_delta,
    _restore_workspace_checkpoint,
    _snapshot_git_workspace,
)


def _git(root: Path, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _repo(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Wynxq Tests")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "base")
    return root


def test_checkpoint_restores_only_files_changed_after_snapshot(tmp_path):
    root = _repo(tmp_path)

    # User work already present before the agent starts must survive undo.
    (root / "tracked.txt").write_text("user change\n", encoding="utf-8")
    (root / "personal.txt").write_text("keep me\n", encoding="utf-8")
    before_all = _snapshot_git_workspace(root)
    assert before_all is not None

    # Simulate one agent run: edit one existing file and create another.
    (root / "tracked.txt").write_text("agent result\n", encoding="utf-8")
    (root / "agent-created.txt").write_text("temporary\n", encoding="utf-8")
    after_all = _snapshot_git_workspace(root)
    before, after = _checkpoint_delta(before_all, after_all)

    assert set(before) == {"agent-created.txt", "tracked.txt"}
    count = _restore_workspace_checkpoint(root, before, after)
    assert count == 2
    assert (root / "tracked.txt").read_text(encoding="utf-8") == "user change\n"
    assert (root / "personal.txt").read_text(encoding="utf-8") == "keep me\n"
    assert not (root / "agent-created.txt").exists()


def test_checkpoint_refuses_to_overwrite_edits_made_after_agent_run(tmp_path):
    root = _repo(tmp_path)
    before_all = _snapshot_git_workspace(root)
    (root / "tracked.txt").write_text("agent result\n", encoding="utf-8")
    after_all = _snapshot_git_workspace(root)
    before, after = _checkpoint_delta(before_all, after_all)

    (root / "tracked.txt").write_text("newer human edit\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after the agent run"):
        _restore_workspace_checkpoint(root, before, after)

    assert (root / "tracked.txt").read_text(encoding="utf-8") == "newer human edit\n"


def test_checkpoint_preserves_executable_mode(tmp_path):
    root = _repo(tmp_path)
    script = root / "tool.sh"
    script.write_text("#!/bin/sh\necho before\n", encoding="utf-8")
    script.chmod(0o755)
    _git(root, "add", "tool.sh")
    _git(root, "commit", "-m", "script")

    before_all = _snapshot_git_workspace(root)
    script.write_text("#!/bin/sh\necho agent\n", encoding="utf-8")
    script.chmod(0o644)
    after_all = _snapshot_git_workspace(root)
    before, after = _checkpoint_delta(before_all, after_all)

    _restore_workspace_checkpoint(root, before, after)
    assert script.read_text(encoding="utf-8") == "#!/bin/sh\necho before\n"
    assert script.stat().st_mode & 0o777 == 0o755
