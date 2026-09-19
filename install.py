#!/usr/bin/env python3
"""Install an isolated, removable Wynxq copy without administrator privileges."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import venv

APP_ID = "io.github.wynxq.Wynxq"
MARKER = ".wynxq-install.json"
MANIFEST = "manifest.json"

_MISSING_SO = re.compile(
    r"(?P<name>[A-Za-z0-9_+.-]+\.so(?:\.[A-Za-z0-9_+.-]+)+)(?::|\s+=>\s+not found)"
)


def absolute(value: str | Path) -> Path:
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    if any(ord(char) < 32 for char in str(path)):
        raise ValueError("Installation paths cannot contain control characters.")
    return path


def xdg_path(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    return absolute(value if value and Path(value).is_absolute() else Path.home() / fallback)


def default_root() -> Path:
    return xdg_path("XDG_DATA_HOME", ".local/share") / "wynxq-app"


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def owned_root(root: Path) -> dict:
    marker = root / MARKER
    if root.is_symlink() or not root.is_dir() or marker.is_symlink() or not marker.is_file():
        raise ValueError(f"Refusing to modify an unowned installation path: {root}")
    try:
        content = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid Wynxq ownership marker: {marker}") from exc
    if content.get("app") != APP_ID or content.get("uid") != os.getuid():
        raise ValueError(f"Installation is not owned by this user: {root}")
    return content


@contextmanager
def install_lock(root: Path):
    lock = root / ".install.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"Another operation may be running. Lock: {lock}") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wynxq-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".wynxq-{uuid.uuid4().hex}"
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fingerprint(path: Path) -> dict | None:
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if path.is_file():
        return {"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if exists(path):
        return {"kind": "other"}
    return None


def read_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not exists(path):
        return {"files": {}, "releases": []}
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe install manifest: {path}")
    result = json.loads(path.read_text())
    if not isinstance(result.get("files"), dict) or not isinstance(result.get("releases"), list):
        raise ValueError("Invalid install manifest.")
    return result


def points_into(path: Path, root: Path) -> bool:
    if not path.is_symlink():
        return False
    target = Path(os.readlink(path))
    if not target.is_absolute():
        target = path.parent / target
    return root == target or root in absolute(target).parents


def check_managed(path: Path, old: dict, root: Path | None = None) -> None:
    actual = fingerprint(path)
    expected = old.get("files", {}).get(str(path))
    if actual is None or (expected is not None and actual == expected):
        return
    if points_into(path, root) if root is not None else False:
        return
    raise ValueError(
        f"Refusing to overwrite a file Wynxq does not recognise: {path}\n"
        f"If it is left over from an older Wynxq, remove it and install again."
    )


def _snapshot(paths: list[Path]) -> dict:
    snapshots = {}
    for path in paths:
        if path.is_symlink():
            snapshots[path] = ("link", os.readlink(path))
        elif path.is_file():
            snapshots[path] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
        elif exists(path):
            raise ValueError(f"Expected a file or symlink: {path}")
        else:
            snapshots[path] = None
    return snapshots


def _restore(snapshots: dict) -> None:
    for path, state in reversed(list(snapshots.items())):
        if state is None:
            path.unlink(missing_ok=True)
        elif state[0] == "link":
            atomic_link(path, state[1])
        else:
            atomic_write(path, state[1], state[2])


def _copy_source(source: Path, destination: Path) -> None:
    destination.mkdir()
    # setup.py builds the C++ core into the wheel. Keep every build input in
    # the isolated release copy so `python3 install.py` behaves like a normal
    # `pip install .` instead of silently falling back to Python-only policy.
    for name in (
        "pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "LICENSE",
        "install.py", "uninstall.py",
    ):
        shutil.copy2(source / name, destination / name)
    for name in ("wynxq", "assets", "native"):
        shutil.copytree(source / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _is_nixos() -> bool:
    try:
        return "nixos" in Path("/etc/os-release").read_text(errors="ignore").lower()
    except OSError:
        return Path("/nix/store").is_dir()


def _nix_closure_paths() -> list[Path]:
    """Return rooted Nix store paths before falling back to the whole store."""
    if not _is_nixos():
        return []
    roots = [Path("/run/current-system")]
    user = os.environ.get("USER")
    if user:
        roots.append(Path("/nix/var/nix/profiles/per-user") / user / "profile")
    paths: list[Path] = []
    seen: set[str] = set()
    nix_store = shutil.which("nix-store")
    if nix_store:
        for root in roots:
            if not root.exists():
                continue
            result = subprocess.run(
                [nix_store, "-qR", str(root)], capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                if line.startswith("/nix/store/") and line not in seen:
                    seen.add(line)
                    paths.append(Path(line))
    return paths


def _library_in_prefix(prefix: Path, name: str) -> Path | None:
    for relative in (
        Path("lib") / name,
        Path("lib64") / name,
        Path("lib/x86_64-linux-gnu") / name,
    ):
        candidate = prefix / relative
        if candidate.exists():
            return candidate.parent
    return None


def _find_nix_library(name: str, closure: list[Path] | None = None) -> Path | None:
    """Find one missing soname in a rooted Nix closure, then in /nix/store."""
    if not _is_nixos() or "/" in name or "\x00" in name:
        return None

    for prefix in (
        Path("/run/current-system/sw"),
        Path.home() / ".nix-profile",
    ):
        found = _library_in_prefix(prefix, name)
        if found:
            return found

    for prefix in closure if closure is not None else _nix_closure_paths():
        found = _library_in_prefix(prefix, name)
        if found:
            return found

    find = shutil.which("find")
    if find and Path("/nix/store").is_dir():
        result = subprocess.run(
            [find, "/nix/store", "-maxdepth", "3", "-name", name, "-print", "-quit"],
            capture_output=True, text=True, check=False,
        )
        match = result.stdout.splitlines()
        if match:
            path = Path(match[0])
            if path.exists():
                return path.parent
    return None


def _missing_library_names(output: str) -> list[str]:
    """Extract missing ELF sonames from Python/import and ldd diagnostics."""
    names: list[str] = []
    for match in _MISSING_SO.finditer(output or ""):
        name = match.group("name")
        if name not in names:
            names.append(name)
    for line in (output or "").splitlines():
        if "=> not found" not in line:
            continue
        name = line.split("=>", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def _runtime_environment(lib_dirs: list[Path] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    dirs = [Path(path) for path in (lib_dirs or []) if Path(path).is_dir()]
    if dirs:
        current = env.get("LD_LIBRARY_PATH", "")
        joined = os.pathsep.join(str(path) for path in dirs)
        env["LD_LIBRARY_PATH"] = joined + (os.pathsep + current if current else "")
    return env


def _resolve_command_libraries(
    command: list[str], *, cwd: Path, lib_dirs: list[Path], closure: list[Path],
    extra_env: dict[str, str] | None = None, attempts: int = 32,
) -> subprocess.CompletedProcess:
    """Run a probe and teach its environment each missing Nix soname in turn."""
    last: subprocess.CompletedProcess | None = None
    for _ in range(attempts):
        env = _runtime_environment(lib_dirs)
        if extra_env:
            env.update(extra_env)
        last = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
        if last.returncode == 0:
            return last
        output = (last.stdout or "") + "\n" + (last.stderr or "")
        missing = _missing_library_names(output)
        added = False
        unresolved: list[str] = []
        for name in missing:
            directory = _find_nix_library(name, closure)
            if directory is None:
                unresolved.append(name)
                continue
            if directory not in lib_dirs:
                print(f"NixOS: found {name} in {directory}", flush=True)
                lib_dirs.append(directory)
                added = True
        if added:
            continue
        if unresolved:
            raise RuntimeError(
                "NixOS is missing native libraries required by Wynxq: "
                + ", ".join(unresolved)
                + ". Add the packages providing them to your NixOS configuration and run the installer again."
            )
        tail = "\n".join(output.strip().splitlines()[-18:])
        raise RuntimeError(f"Wynxq's native dependency check failed:\n{tail}")
    output = "" if last is None else ((last.stdout or "") + "\n" + (last.stderr or ""))
    raise RuntimeError("Could not resolve Wynxq's native dependencies after repeated attempts.\n" + output[-4000:])


def _scan_elf_dependencies(environment: Path, lib_dirs: list[Path], closure: list[Path]) -> None:
    """Resolve native dependencies of the Qt modules and platform plugins we use."""
    if not _is_nixos():
        return
    ldd = shutil.which("ldd")
    if not ldd:
        return

    site_packages = list((environment / "lib").glob("python*/site-packages"))
    if not site_packages:
        return
    site = site_packages[0]
    patterns = (
        "shiboken6/Shiboken*.so",
        "PySide6/QtCore*.so",
        "PySide6/QtGui*.so",
        "PySide6/QtQml*.so",
        "PySide6/QtQuick*.so",
        "PySide6/QtWidgets*.so",
        "PySide6/Qt/lib/libQt6Core.so*",
        "PySide6/Qt/lib/libQt6Gui.so*",
        "PySide6/Qt/lib/libQt6Qml.so*",
        "PySide6/Qt/lib/libQt6Quick.so*",
        "PySide6/Qt/plugins/platforms/libqoffscreen.so",
        "PySide6/Qt/plugins/platforms/libqxcb.so",
        "PySide6/Qt/plugins/platforms/libqwayland*.so",
    )
    targets: list[Path] = []
    for pattern in patterns:
        for target in site.glob(pattern):
            if target.is_file() and target not in targets:
                targets.append(target)

    for _ in range(16):
        missing: list[str] = []
        env = _runtime_environment(lib_dirs)
        for target in targets:
            result = subprocess.run([ldd, str(target)], env=env, capture_output=True, text=True, check=False)
            for name in _missing_library_names((result.stdout or "") + "\n" + (result.stderr or "")):
                if name not in missing:
                    missing.append(name)
        if not missing:
            return
        added = False
        unresolved: list[str] = []
        for name in missing:
            directory = _find_nix_library(name, closure)
            if directory is None:
                unresolved.append(name)
                continue
            if directory not in lib_dirs:
                print(f"NixOS: found {name} in {directory}", flush=True)
                lib_dirs.append(directory)
                added = True
        if unresolved:
            print("NixOS: optional Qt plugin libraries not present: " + ", ".join(unresolved), flush=True)
        if not added:
            return


def _build_environment(release: Path) -> list[Path]:
    environment = release / "venv"
    print("Creating an isolated Python environment…", flush=True)
    try:
        venv.EnvBuilder(with_pip=True).create(environment)
    except Exception as exc:
        raise RuntimeError("Python venv support is required. On Debian/Ubuntu: sudo apt install python3-venv") from exc
    python = environment / "bin/python"
    print("Installing Wynxq and its GUI dependencies (first install may take a few minutes)…", flush=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(release / "source")],
        check=True,
    )

    if not _is_nixos():
        subprocess.run(
            [str(python), "-c", "import wynxq, PySide6, httpx, dbus_next, PIL, Xlib"],
            check=True,
        )
        return []

    print("NixOS detected — resolving native Qt runtime libraries…", flush=True)
    closure = _nix_closure_paths()
    lib_dirs: list[Path] = []
    _scan_elf_dependencies(environment, lib_dirs, closure)

    probe = (
        "import wynxq, httpx, dbus_next, PIL, Xlib; "
        "from PySide6 import QtCore, QtGui, QtQml, QtQuick, QtQuickControls2, QtWidgets"
    )
    _resolve_command_libraries(
        [str(python), "-c", probe], cwd=release, lib_dirs=lib_dirs, closure=closure
    )

    console = environment / "bin/wynxq"
    if console.exists():
        _resolve_command_libraries(
            [str(console), "--smoke-test"], cwd=release, lib_dirs=lib_dirs, closure=closure,
            extra_env={"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        )
    return lib_dirs


def _launcher_runtime_prefix(lib_dirs: list[Path] | None = None) -> str:
    dirs = [str(Path(path)) for path in (lib_dirs or [])]
    if not dirs:
        return ""
    joined = ":".join(dirs)
    return f"export LD_LIBRARY_PATH={shlex.quote(joined)}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}\n"


def desktop_argument(value: Path) -> str:
    argument = str(value).replace("%", "%%")
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$")):
        argument = argument.replace(old, new)
    return '"' + argument.replace("\\", "\\\\") + '"'


def install(source: Path, root: Path | None = None, bin_dir: Path | None = None) -> Path:
    source = absolute(source)
    root = absolute(root or default_root())
    bin_dir = absolute(bin_dir or Path.home() / ".local/bin")
    data = xdg_path("XDG_DATA_HOME", ".local/share")
    desktop = data / "applications" / f"{APP_ID}.desktop"
    icon = data / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    launcher_link = bin_dir / "wynxq"
    if not (source / "wynxq/__main__.py").is_file():
        raise ValueError("Run this installer from a complete Wynxq checkout.")
    if root == source or root in source.parents or source in root.parents:
        raise ValueError("Install directory must be outside the source checkout.")
    if bin_dir == root or root in bin_dir.parents:
        raise ValueError("Launcher directory must be outside the installation directory.")
    fresh = not exists(root)
    if fresh:
        root.mkdir(parents=True)
        atomic_write(root / MARKER, json.dumps({"app": APP_ID, "uid": os.getuid(), "format": 1}).encode())
    owned_root(root)
    release = None
    try:
        with install_lock(root):
            old = read_manifest(root)
            internal = [root / "wynxq", root / "uninstall.py", root / "current"]
            external = [launcher_link, desktop, icon]
            for path in internal + external:
                check_managed(path, old, root)
            previous_external = set(old.get("external", []))
            if previous_external and previous_external != {str(p) for p in external}:
                raise ValueError("Install destinations changed; uninstall the existing copy first (your data is kept).")
            releases = root / "releases"
            if releases.is_symlink() or (exists(releases) and not releases.is_dir()):
                raise ValueError(f"Unsafe releases directory: {releases}")
            releases.mkdir(exist_ok=True)
            release_id = uuid.uuid4().hex
            release = releases / release_id
            release.mkdir()
            atomic_write(release / ".wynxq-release", APP_ID.encode())
            _copy_source(source, release / "source")
            runtime_dirs = _build_environment(release) or []
            snapshots = _snapshot(internal + external + [root / MANIFEST])
            try:
                launcher = (
                    "#!/bin/sh\nset -eu\n"
                    f"export WYNXQ_INSTALL_ROOT={shlex.quote(str(root))}\n"
                    + _launcher_runtime_prefix(runtime_dirs)
                    + 'if [ "${1-}" = "--uninstall" ]; then\n'
                    '  shift\n'
                    '  exec "$WYNXQ_INSTALL_ROOT/current/venv/bin/python" "$WYNXQ_INSTALL_ROOT/uninstall.py" --install-root "$WYNXQ_INSTALL_ROOT" "$@"\n'
                    'fi\n'
                    'cd "$WYNXQ_INSTALL_ROOT/current"\n'
                    'exec "$WYNXQ_INSTALL_ROOT/current/venv/bin/wynxq" "$@"\n'
                )
                atomic_write(root / "wynxq", launcher.encode(), 0o755)
                atomic_link(root / "uninstall.py", "current/source/uninstall.py")
                atomic_link(root / "current", f"releases/{release_id}")
                atomic_link(launcher_link, str(root / "wynxq"))
                atomic_write(icon, (source / "assets/wynxq.svg").read_bytes())
                entry = (
                    "[Desktop Entry]\nType=Application\nVersion=1.0\nName=Wynxq\n"
                    "Comment=Your local AI workbench\n"
                    f"Exec={desktop_argument(root / 'wynxq')}\n"
                    f"Icon={str(icon).replace(chr(92), chr(92) * 2)}\n"
                    "Terminal=false\nCategories=Utility;Development;\nKeywords=AI;Ollama;Assistant;Copilot;\n"
                    "StartupWMClass=wynxq\n"
                    "Actions=QuickBar;NewChat;\n"
                    "\n[Desktop Action QuickBar]\nName=Quick bar\n"
                    f"Exec={desktop_argument(root / 'wynxq')} --quick\n"
                    "\n[Desktop Action NewChat]\nName=New chat\n"
                    f"Exec={desktop_argument(root / 'wynxq')}\n"
                )
                atomic_write(desktop, entry.encode())
                manifest = {
                    "files": {str(path): fingerprint(path) for path in internal + external},
                    "external": [str(path) for path in external],
                    "releases": old.get("releases", []) + [release_id],
                    "runtime_lib_dirs": [str(path) for path in runtime_dirs],
                    "data_dirs": old.get("data_dirs", [
                        str(data / "wynxq"),
                        str(xdg_path("XDG_CONFIG_HOME", ".config") / "wynxq"),
                        str(xdg_path("XDG_CACHE_HOME", ".cache") / "wynxq"),
                    ]),
                }
                atomic_write(root / MANIFEST, json.dumps(manifest, indent=2).encode())
            except BaseException:
                _restore(snapshots)
                raise
    except BaseException:
        if release is not None and release.is_dir() and not release.is_symlink():
            shutil.rmtree(release)
        if fresh:
            owned_root(root)
            shutil.rmtree(root)
        raise
    return launcher_link


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install-root", type=Path, default=default_root(),
        help="App directory (default: XDG_DATA_HOME/wynxq-app)",
    )
    parser.add_argument(
        "--bin-dir", type=Path, default=Path.home() / ".local/bin",
        help="Launcher directory (default: ~/.local/bin)",
    )
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Wynxq currently supports Linux.")
    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required.")
    if os.geteuid() == 0:
        parser.error("Run this installer as your normal user, without sudo.")
    try:
        launcher = install(Path(__file__).resolve().parent, args.install_root, args.bin_dir)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"\nInstall failed; previous installation preserved.\n{exc}", file=sys.stderr)
        return 1
    print(f"\nWynxq installed. Open Wynxq from your application menu or run:\n  {shlex.quote(str(launcher))}")
    if str(launcher.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Your shell PATH does not include {launcher.parent}; the application menu still works.")
    print(f"Remove it any time: {shlex.quote(str(launcher))} --uninstall")
    print("Ollama and models are managed separately. Your model files are never changed by this installer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())