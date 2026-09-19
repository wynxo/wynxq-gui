"""What the Changes panel reads from Git, against a real repository."""
from pathlib import Path
import shutil
import subprocess

import pytest

from wynxq import diffs

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(root, *arguments):
    return subprocess.run(["git", *arguments], cwd=str(root), capture_output=True,
                          text=True, check=True, stdin=subprocess.DEVNULL)


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q", "-b", "work")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "kept.py").write_text("one\ntwo\nthree\n")
    (tmp_path / "gone.txt").write_text("bye\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "first")
    return tmp_path


def test_git_is_resolved_to_an_absolute_executable_before_workers_start():
    assert diffs.GIT_EXECUTABLE
    assert Path(diffs.GIT_EXECUTABLE).is_absolute()


def test_a_plain_folder_is_reported_as_not_a_repository(tmp_path):
    assert diffs.is_repository(tmp_path) is False
    result = diffs.changed_files(tmp_path)
    assert result["repository"] is False
    assert result["files"] == []


def test_a_clean_repository_has_a_branch_and_no_changes(repository):
    result = diffs.changed_files(repository)
    assert result["repository"] is True
    assert result["branch"] == "work"
    assert result["files"] == []
    assert result["added"] == 0 and result["removed"] == 0


def test_every_kind_of_change_is_reported_with_its_line_counts(repository):
    (repository / "kept.py").write_text("one\nTWO\nthree\nfour\n")
    (repository / "gone.txt").unlink()
    (repository / "fresh.md").write_text("# new\nsecond line\n")

    result = diffs.changed_files(repository)
    by_path = {entry["path"]: entry for entry in result["files"]}

    assert by_path["kept.py"]["status"] == "M"
    assert by_path["kept.py"]["added"] == 2 and by_path["kept.py"]["removed"] == 1
    assert by_path["gone.txt"]["status"] == "D"
    assert by_path["fresh.md"]["status"] == "?"
    assert by_path["fresh.md"]["untracked"] is True
    assert by_path["fresh.md"]["added"] == 2
    assert result["added"] == sum(e["added"] for e in result["files"])


def test_a_path_keeps_its_name_and_its_folder_apart(repository):
    (repository / "pkg").mkdir()
    (repository / "pkg" / "mod.py").write_text("x\n")
    entry = next(e for e in diffs.changed_files(repository)["files"]
                 if e["path"] == "pkg/mod.py")
    assert entry["name"] == "mod.py"
    assert entry["directory"] == "pkg"


def test_a_staged_change_still_counts(repository):
    (repository / "kept.py").write_text("one\ntwo\nthree\nfour\n")
    git(repository, "add", "kept.py")
    entry = diffs.changed_files(repository)["files"][0]
    assert entry["staged"] is True
    assert entry["added"] == 1


# ------------------------------------------------------------------- diffs
def test_a_diff_comes_back_as_rows_with_both_line_numbers(repository):
    (repository / "kept.py").write_text("one\nTWO\nthree\n")
    rows = diffs.file_diff(repository, "kept.py")["rows"]
    kinds = [row["type"] for row in rows]
    assert "hunk" in kinds and "add" in kinds and "remove" in kinds

    removed = next(row for row in rows if row["type"] == "remove")
    added = next(row for row in rows if row["type"] == "add")
    assert removed["text"] == "two" and removed["old"] == 2
    assert added["text"] == "TWO" and added["new"] == 2

    context = next(row for row in rows if row["type"] == "context")
    assert context["old"] > 0 and context["new"] > 0


def test_an_untracked_file_diffs_against_nothing(repository):
    (repository / "fresh.md").write_text("alpha\nbeta\n")
    rows = diffs.file_diff(repository, "fresh.md", untracked=True)["rows"]
    assert [row["text"] for row in rows if row["type"] == "add"] == ["alpha", "beta"]
    assert not any(row["type"] == "remove" for row in rows)


def test_a_binary_diff_says_so_instead_of_printing_bytes(repository):
    (repository / "blob.bin").write_bytes(bytes(range(256)) * 40)
    git(repository, "add", "blob.bin")
    git(repository, "commit", "-qm", "blob")
    (repository / "blob.bin").write_bytes(bytes(range(255, -1, -1)) * 40)
    result = diffs.file_diff(repository, "blob.bin")
    assert result["binary"] is True
    assert result["rows"] == []


def test_a_diff_is_bounded(repository, monkeypatch):
    monkeypatch.setattr(diffs, "MAX_DIFF_LINES", 20)
    (repository / "kept.py").write_text("".join(f"line {n}\n" for n in range(500)))
    rows = diffs.file_diff(repository, "kept.py")["rows"]
    assert len(rows) <= 21
    assert rows[-1]["text"] == "Diff truncated"


def test_the_committed_version_can_be_read_back(repository):
    (repository / "kept.py").write_text("changed\n")
    assert diffs.original_text(repository, "kept.py") == "one\ntwo\nthree\n"


# ----------------------------------------------------------------- reverting
def test_reverting_restores_a_tracked_file(repository):
    (repository / "kept.py").write_text("ruined\n")
    result = diffs.revert_file(repository, "kept.py")
    assert result["ok"] is True
    assert (repository / "kept.py").read_text() == "one\ntwo\nthree\n"


def test_reverting_an_untracked_file_deletes_it(repository):
    (repository / "fresh.md").write_text("x")
    result = diffs.revert_file(repository, "fresh.md", untracked=True)
    assert result["ok"] is True and result["deleted"] is True
    assert not (repository / "fresh.md").exists()


def test_reverting_refuses_a_path_outside_the_project(repository, tmp_path):
    victim = tmp_path.parent / "victim.txt"
    victim.write_text("mine")
    result = diffs.revert_file(repository, str(victim))
    assert result["ok"] is False
    assert victim.read_text() == "mine"
