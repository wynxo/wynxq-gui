"""Bounded, conflict-safe workspace checkpoints for Work mode.

Snapshots and restores are isolated here because they are filesystem policy,
not UI/controller state. The controller only asks for begin/finalize/restore.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

_CHECKPOINT_MAX_FILES = 2500
_CHECKPOINT_MAX_FILE_BYTES = 8 * 1024 * 1024
_CHECKPOINT_MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _checkpoint_entry(path: Path):
    """Capture one project path without following symlinks."""
    if path.is_symlink():
        return ("link", os.readlink(path))
    try:
        stat = path.stat()
    except FileNotFoundError:
        return ("missing",)
    if not path.is_file():
        raise ValueError(f"Unsupported checkpoint path: {path}")
    if stat.st_size > _CHECKPOINT_MAX_FILE_BYTES:
        raise OverflowError(f"{path.name} is too large for a safe run checkpoint")
    return ("file", stat.st_mode & 0o777, path.read_bytes())


def _git_checkpoint_paths(root: Path):
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    paths = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        paths.append(relative)
    return paths


def _snapshot_git_workspace(root: str | Path, selected=None):
    """Snapshot source-controlled + nonignored project files for one run.

    This is intentionally bounded. If a workspace is too large to snapshot
    safely, Undo is simply unavailable rather than pretending a partial restore
    could be trusted.
    """
    base = Path(root).expanduser().resolve()
    paths = list(selected) if selected is not None else _git_checkpoint_paths(base)
    if paths is None or len(paths) > _CHECKPOINT_MAX_FILES:
        return None
    snapshot, total = {}, 0
    try:
        for relative in paths:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                return None
            entry = _checkpoint_entry(base / candidate)
            if entry[0] == "file":
                total += len(entry[2])
            elif entry[0] == "link":
                total += len(os.fsencode(entry[1]))
            if total > _CHECKPOINT_MAX_TOTAL_BYTES:
                return None
            snapshot[relative] = entry
    except (OSError, ValueError, OverflowError):
        return None
    return snapshot


def _checkpoint_delta(before: dict, after: dict):
    missing = ("missing",)
    paths = sorted(set(before) | set(after))
    changed = [path for path in paths
               if before.get(path, missing) != after.get(path, missing)]
    if not changed:
        return {}, {}
    return ({path: before.get(path, missing) for path in changed},
            {path: after.get(path, missing) for path in changed})


def _restore_workspace_checkpoint(root: str | Path, before: dict, after: dict):
    """Restore only paths changed by the run, refusing to clobber newer work."""
    base = Path(root).expanduser().resolve()
    paths = sorted(set(before) | set(after))
    current = _snapshot_git_workspace(base, paths)
    if current is None:
        raise RuntimeError("The workspace can no longer be verified safely.")
    missing = ("missing",)
    for relative in paths:
        if current.get(relative, missing) != after.get(relative, missing):
            raise RuntimeError("A file changed after the agent run. Undo was cancelled to protect newer work.")

    for relative in paths:
        target = base / Path(relative)
        entry = before.get(relative, missing)
        kind = entry[0]
        if kind == "missing":
            if target.is_symlink() or target.exists():
                if target.is_dir() and not target.is_symlink():
                    raise RuntimeError(f"Refusing to remove directory {relative}.")
                target.unlink()
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            if target.is_dir() and not target.is_symlink():
                raise RuntimeError(f"Refusing to replace directory {relative}.")
            target.unlink()

        if kind == "link":
            target.symlink_to(entry[1])
        elif kind == "file":
            target.write_bytes(entry[2])
            target.chmod(entry[1])
        else:
            raise RuntimeError(f"Unknown checkpoint entry for {relative}.")
    return len(paths)
