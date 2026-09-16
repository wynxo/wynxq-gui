"""What changed in the project, and what the change looks like.

Git is the source of truth when the project is a repository, because it already
knows what "changed" means. Outside a repository the Changes panel says so
rather than inventing a baseline it cannot defend.

Every call is bounded and read-only. Reverting is deliberately *not* here: it
belongs behind the controller's confirmation, not behind a helper anyone can
call.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .background import serialized_io

GIT_TIMEOUT = 12
MAX_FILES = 500
MAX_DIFF_LINES = 4000

STATUS_LABELS = {
    "M": "Modified", "A": "Added", "D": "Deleted", "R": "Renamed",
    "C": "Copied", "?": "Untracked", "U": "Conflicted", "T": "Type changed",
}


def _git(root, *arguments, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "--no-optional-locks", *arguments],
        cwd=str(root), capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def is_repository(root) -> bool:
    if not root:
        return False
    try:
        directory = Path(root).expanduser()
        if not directory.is_dir():
            return False
        result = _git(directory, "rev-parse", "--is-inside-work-tree", timeout=6)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def branch_name(root) -> str:
    try:
        result = _git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=6)
    except (OSError, subprocess.SubprocessError):
        return ""
    name = result.stdout.strip()
    if result.returncode != 0 or not name:
        return ""
    return "detached" if name == "HEAD" else name


def _parse_porcelain(output: str) -> list[dict]:
    """`git status --porcelain -z` into one entry per path."""
    files: list[dict] = []
    fields = output.split("\0")
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4:
            continue
        staged, unstaged, path = record[0], record[1], record[3:]
        original = ""
        if staged in ("R", "C"):
            # A rename record is followed by its source path.
            original = fields[index] if index < len(fields) else ""
            index += 1
        code = staged if staged not in (" ", "?") else unstaged
        if staged == "?" or unstaged == "?":
            code = "?"
        files.append({
            "path": path,
            "original": original,
            "status": code,
            "statusLabel": STATUS_LABELS.get(code, "Changed"),
            "staged": staged not in (" ", "?"),
            "untracked": code == "?",
        })
        if len(files) >= MAX_FILES:
            break
    return files


def _numstat(root, *arguments) -> dict[str, tuple[int, int]]:
    try:
        result = _git(root, "diff", "--numstat", "-z", *arguments)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    counts: dict[str, tuple[int, int]] = {}
    fields = [field for field in result.stdout.split("\0") if field != ""]
    index = 0
    while index < len(fields):
        parts = fields[index].split("\t")
        index += 1
        if len(parts) < 3:
            continue
        added, removed, path = parts[0], parts[1], parts[2]
        if not path:
            # Rename: the two following records are the old and new paths.
            if index + 1 < len(fields):
                path = fields[index + 1]
                index += 2
            else:
                break
        counts[path] = (
            0 if added == "-" else int(added or 0),
            0 if removed == "-" else int(removed or 0),
        )
    return counts


def _count_new_file(root, path) -> tuple[int, int]:
    try:
        target = Path(root) / path
        if not target.is_file() or target.stat().st_size > 2_000_000:
            return (0, 0)
        with target.open("rb") as handle:
            sample = handle.read(8192)
        if b"\0" in sample:
            return (0, 0)
        text = target.read_text("utf-8", errors="replace")
    except OSError:
        return (0, 0)
    return (text.count("\n") + (1 if text and not text.endswith("\n") else 0), 0)


@serialized_io
def changed_files(root) -> dict:
    """Every uncommitted change in the project, with line counts."""
    if not is_repository(root):
        return {"repository": False, "branch": "", "files": [], "added": 0,
                "removed": 0, "error": ""}
    try:
        status = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
    except subprocess.TimeoutExpired:
        return {"repository": True, "branch": "", "files": [], "added": 0,
                "removed": 0, "error": "git status timed out"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"repository": True, "branch": "", "files": [], "added": 0,
                "removed": 0, "error": str(exc)}
    if status.returncode != 0:
        return {"repository": True, "branch": "", "files": [], "added": 0,
                "removed": 0, "error": status.stderr.strip()[:200]}

    files = _parse_porcelain(status.stdout)
    worktree = _numstat(root)
    staged = _numstat(root, "--cached")

    total_added = total_removed = 0
    for entry in files:
        path = entry["path"]
        if entry["untracked"]:
            added, removed = _count_new_file(root, path)
        else:
            worktree_counts = worktree.get(path, (0, 0))
            staged_counts = staged.get(path, (0, 0))
            added = worktree_counts[0] + staged_counts[0]
            removed = worktree_counts[1] + staged_counts[1]
        entry["added"] = added
        entry["removed"] = removed
        entry["name"] = Path(path).name
        parent = str(Path(path).parent)
        entry["directory"] = "" if parent == "." else parent
        total_added += added
        total_removed += removed

    return {"repository": True, "branch": branch_name(root), "files": files,
            "added": total_added, "removed": total_removed, "error": ""}


def _parse_unified(text: str) -> list[dict]:
    """A unified diff into rows the viewer can render without re-parsing."""
    rows: list[dict] = []
    old_line = new_line = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git") or raw.startswith("index ") \
                or raw.startswith("--- ") or raw.startswith("+++ ") \
                or raw.startswith("new file") or raw.startswith("deleted file") \
                or raw.startswith("similarity index") or raw.startswith("rename "):
            continue
        if raw.startswith("@@"):
            head = raw.split("@@")
            marker = head[1].strip() if len(head) > 1 else ""
            try:
                old_part, new_part = marker.split(" ")
                old_line = int(old_part[1:].split(",")[0])
                new_line = int(new_part[1:].split(",")[0])
            except (ValueError, IndexError):
                old_line = new_line = 1
            rows.append({"type": "hunk", "text": raw.rstrip(), "old": 0, "new": 0})
            continue
        if raw.startswith("+"):
            rows.append({"type": "add", "text": raw[1:], "old": 0, "new": new_line})
            new_line += 1
        elif raw.startswith("-"):
            rows.append({"type": "remove", "text": raw[1:], "old": old_line, "new": 0})
            old_line += 1
        elif raw.startswith("\\"):
            rows.append({"type": "meta", "text": raw[1:].strip(), "old": 0, "new": 0})
        else:
            rows.append({"type": "context", "text": raw[1:] if raw else "",
                         "old": old_line, "new": new_line})
            old_line += 1
            new_line += 1
        if len(rows) >= MAX_DIFF_LINES:
            rows.append({"type": "meta", "text": "Diff truncated", "old": 0, "new": 0})
            break
    return rows


@serialized_io
def file_diff(root, path, untracked: bool = False) -> dict:
    """The diff for one file, as rows. An added file diffs against nothing."""
    result = {"path": str(path), "rows": [], "error": "", "binary": False}
    if not is_repository(root):
        result["error"] = "Not a Git repository"
        return result
    try:
        if untracked:
            # `--no-index` gives an added file the same shape as any other.
            process = _git(root, "diff", "--no-index", "--no-color",
                           "--unified=3", "/dev/null", str(path))
            text = process.stdout
        else:
            process = _git(root, "diff", "--no-color", "--unified=3", "HEAD", "--", str(path))
            text = process.stdout
            if not text.strip():
                process = _git(root, "diff", "--no-color", "--unified=3", "--", str(path))
                text = process.stdout
    except subprocess.TimeoutExpired:
        result["error"] = "git diff timed out"
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)
        return result

    if "Binary files" in text or "GIT binary patch" in text:
        result["binary"] = True
        result["error"] = "Binary file"
        return result
    if not text.strip():
        result["error"] = "No textual changes"
        return result
    result["rows"] = _parse_unified(text)
    return result


def original_text(root, path) -> str:
    """The committed version of a file, for side-by-side or revert preview."""
    if not is_repository(root):
        return ""
    try:
        result = _git(root, "show", f"HEAD:{path}")
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def revert_file(root, path, untracked: bool = False) -> dict:
    """Throw away one file's uncommitted changes.

    Destructive, and named so. The controller only calls this behind an
    explicit confirmation; an untracked file is deleted rather than restored,
    because there is nothing to restore it to.
    """
    if not is_repository(root):
        return {"ok": False, "error": "Not a Git repository"}
    target = Path(root).expanduser().resolve() / str(path)
    try:
        target.resolve().relative_to(Path(root).expanduser().resolve())
    except ValueError:
        return {"ok": False, "error": "That path is outside the project"}
    try:
        if untracked:
            if target.is_file():
                target.unlink()
            return {"ok": True, "error": "", "deleted": True}
        restore = _git(root, "restore", "--staged", "--worktree", "--", str(path))
        if restore.returncode != 0:
            # Older Git without `restore`.
            _git(root, "reset", "HEAD", "--", str(path))
            checkout = _git(root, "checkout", "--", str(path))
            if checkout.returncode != 0:
                return {"ok": False, "error": checkout.stderr.strip()[:200]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "error": "", "deleted": False}
