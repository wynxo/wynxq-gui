"""The Wynxq rename is structural, not just visible copy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".qml", ".md", ".toml", ".yml", ".yaml", ".json", ".txt",
    ".svg", ".sh", ".service", ".ini", ".cfg", ".conf", ".xml", ".qrc",
    ".h", ".hpp", ".c", ".cc", ".cpp", ".cxx", ".in",
}


def test_old_product_namespace_is_gone():
    old = "wyn" + "xo"
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path == Path(__file__):
            continue
        if old in path.as_posix().casefold():
            offenders.append(path.relative_to(ROOT).as_posix())
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and "." in path.name:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            folded = line.casefold()
            if old not in folded:
                continue
            # The repository still belongs to the GitHub account "wynxo".
            # That external owner is not the application/package name.
            if "github.com/" + old + "/" in folded:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], "old Wynxq namespace remains: " + ", ".join(offenders)


def test_cli_package_qml_and_desktop_identity_are_wynxq():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    entry = (ROOT / "wynxq" / "__main__.py").read_text(encoding="utf-8")
    qmldir = (ROOT / "wynxq" / "ui" / "Wynxq" / "qmldir").read_text(encoding="utf-8")
    assert 'name = "wynxq"' in pyproject
    assert 'wynxq = "wynxq.__main__:main"' in pyproject
    assert 'app.setApplicationName("Wynxq")' in entry
    assert 'app.setDesktopFileName("io.github.wynxq.Wynxq")' in entry
    assert qmldir.startswith("module Wynxq\n")


def test_snapshot_catalog_is_process_isolated_and_bounded():
    entry = (ROOT / "wynxq" / "__main__.py").read_text(encoding="utf-8")
    assert "def _snapshot_isolated" in entry
    assert 'sys.executable, "-m", "wynxq"' in entry
    assert 'command.extend(["--preview-overlay", overlay])' in entry
    assert "subprocess.run(command, check=False, timeout=20)" in entry
