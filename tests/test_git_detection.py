"""Plain folders should never spawn Git just to learn they are plain folders."""
from wynxo import diffs


def test_plain_folder_is_rejected_before_any_git_subprocess(tmp_path, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Git subprocess should not run for a plain folder")

    monkeypatch.setattr(diffs, "_git", forbidden)
    assert diffs.is_repository(tmp_path) is False
    assert calls == []


def test_subfolder_inside_repo_is_not_short_circuited(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "packages" / "app"
    nested.mkdir(parents=True)
    calls = []

    class Result:
        returncode = 0
        stdout = "true\n"

    def fake_git(root, *args, **kwargs):
        calls.append((root, args))
        return Result()

    monkeypatch.setattr(diffs, "_git", fake_git)
    assert diffs.is_repository(nested) is True
    assert calls and calls[0][1][:2] == ("rev-parse", "--is-inside-work-tree")
