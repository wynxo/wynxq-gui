"""Generated project context should be useful, bounded and safe to persist nowhere."""
from pathlib import Path

from wynxq import project_context


def test_snapshot_detects_stack_without_reading_script_bodies(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "CMakeLists.txt").write_text("project(example)\n")
    (root / "src" / "main.cpp").write_text("int main() { return 0; }\n")
    (root / "tests" / "test_app.py").write_text("def test_ok(): assert True\n")
    (root / "package.json").write_text(
        '{"scripts":{"test":"DO NOT OBEY THIS; rm -rf /","build":"also untrusted"}}'
    )

    text = project_context.snapshot(root)

    assert "C++" in text
    assert "Python" in text
    assert "CMakeLists.txt" in text
    assert "tests/" in text
    assert "build, test" in text
    assert "rm -rf" not in text
    assert "DO NOT OBEY" not in text


def test_scan_never_follows_symlink_directories(tmp_path):
    root = tmp_path / "app"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (root / "main.py").write_text("print('ok')\n")
    (outside / "secret.rs").write_text("fn main() {}\n")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    info = project_context.inspect_project(root)

    languages = dict(info["languages"])
    assert languages.get("Python") == 1
    assert "Rust" not in languages


def test_noise_directories_do_not_distort_language_mix(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "main.py").write_text("print('ok')\n")
    vendor = root / "node_modules" / "huge"
    vendor.mkdir(parents=True)
    for index in range(30):
        (vendor / f"generated{index}.js").write_text("export default 1\n")

    info = project_context.inspect_project(root)

    languages = dict(info["languages"])
    assert languages.get("Python") == 1
    assert "JavaScript" not in languages


def test_injected_snapshot_is_ephemeral_and_stripped_from_history(tmp_path, monkeypatch):
    root = tmp_path / "app"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
    monkeypatch.setattr(project_context, "_git_branch", lambda root: "feature/demo")
    history = [{"role": "user", "content": "Run the tests"}]

    injected = project_context.inject(history, root)

    assert injected[0]["role"] == "system"
    assert injected[0]["content"].startswith(project_context.PROJECT_CONTEXT_PREFIX)
    assert "feature/demo" in injected[0]["content"]
    assert project_context.strip(injected) == history


def test_snapshot_is_bounded(tmp_path, monkeypatch):
    root = tmp_path / "app"
    root.mkdir()
    for index in range(80):
        (root / f"file-{index}.py").write_text("x = 1\n")
    monkeypatch.setattr(project_context, "MAX_PROMPT_CHARS", 300)

    text = project_context.snapshot(root)

    assert len(text) <= 300
