"""The workspace file tree, and reading a single file for the viewer.

Nothing here touches Qt. The dock owns the models; this module owns the rules:
what counts as a project file, how big a file the viewer will open, and — the
part that matters most — that every path handed back to the UI is provably
inside the project the user chose.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .background import serialized_io
from .native_core import native_core

# A directory listing is cheap, but a node_modules with 40 000 entries is not.
MAX_ENTRIES = 4000
# Recursive search has a larger global budget, shared across every visited
# directory. It is still bounded so a generated/vendor tree cannot lock the UI.
MAX_SEARCH_ENTRIES = 20000
# The viewer is a viewer, not an editor for a 400 MB core dump.
MAX_TEXT_BYTES = 1_500_000
MAX_IMAGE_BYTES = 12_000_000
# Remember only a bounded set of files the viewer actually opened. The value is
# a content digest, not an mtime: external tools can rewrite a file to the same
# size inside one timestamp tick, and that must still count as a conflict.
MAX_TRACKED_READS = 512
_READ_VERSIONS: dict[str, bytes] = {}

# Folders nobody opens a project to read. Hidden entries are filtered
# separately, so `.github` is still reachable when hidden files are shown.
NOISE_DIRECTORIES = frozenset({
    "node_modules", "__pycache__", ".git", ".hg", ".svn", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".venv", "venv", "env",
    ".gradle", ".idea", ".vscode", "dist", "build", "target", ".next",
    ".cache", ".DS_Store", "site-packages", ".eggs",
})

# Extension -> the highlighter language name used by wynxq.markdown.
LANGUAGES = {
    ".py": "python", ".pyi": "python", ".qml": "qml", ".js": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".json": "json",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "bash",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".rs": "rust", ".go": "go", ".rb": "ruby", ".java": "java",
    ".kt": "kotlin", ".swift": "swift", ".php": "php", ".lua": "lua",
    ".sql": "sql", ".html": "html", ".htm": "html", ".xml": "xml",
    ".css": "css", ".scss": "css", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".md": "markdown",
    ".markdown": "markdown", ".rst": "markdown", ".txt": "", ".csv": "",
    ".desktop": "ini", ".gitignore": "", ".dockerfile": "bash",
}

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"})

# A file type deserves a shape in the tree, not a different icon family per
# language. Five groups is enough to scan a directory quickly.
KIND_BY_SUFFIX = {
    **{suffix: "code" for suffix in (
        ".py", ".pyi", ".qml", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
        ".c", ".h", ".cpp", ".cc", ".hpp", ".rs", ".go", ".rb", ".java",
        ".kt", ".swift", ".php", ".lua", ".sh", ".bash", ".zsh", ".sql")},
    **{suffix: "config" for suffix in (
        ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
        ".env", ".lock", ".desktop", ".xml")},
    **{suffix: "doc" for suffix in (".md", ".markdown", ".rst", ".txt", ".csv", ".pdf")},
    **{suffix: "image" for suffix in IMAGE_SUFFIXES},
}


def language_for(path) -> str:
    """The highlighter language for a path, or '' when there isn't one."""
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    if name in {"Dockerfile", "Makefile"}:
        return "bash" if name == "Dockerfile" else ""
    if name.startswith(".") and not suffix:
        return ""
    return LANGUAGES.get(suffix, "")


def kind_for(path, is_dir: bool = False) -> str:
    if is_dir:
        return "folder"
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "file")


def human_size(count) -> str:
    try:
        size = float(count)
    except (TypeError, ValueError):
        return ""
    if size < 1024:
        return f"{int(size)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if size >= 100 else f"{size:.1f} {unit}"
    return ""


def explain(error: Exception, what: str = "That file") -> str:
    """An OSError as a sentence.

    `[Errno 2] No such file or directory: '/home/you/…'` tells the user the
    thing they already clicked on is gone, in the least useful possible words.
    """
    if isinstance(error, ValueError):
        return str(error)
    number = getattr(error, "errno", None)
    if number == 2:
        return f"{what} is no longer there."
    if number == 13:
        return f"{what} cannot be read — check its permissions."
    if number == 21:
        return f"{what} is a folder."
    if number == 40:
        return f"{what} is behind a loop of symbolic links."
    reason = getattr(error, "strerror", None) or str(error)
    return f"{what} could not be read: {reason}."


def resolve_within(root, candidate) -> Path:
    """Resolve `candidate` and prove it is inside `root`.

    Every path the dock hands to the UI, and every path the UI hands back,
    goes through here. Symlinks are resolved *before* the check, so a link
    pointing out of the project is rejected rather than followed.
    """
    base = Path(root).expanduser().resolve(strict=True)
    target = Path(candidate).expanduser()
    if not target.is_absolute():
        target = base / target
    target = target.resolve(strict=False)
    if target != base and base not in target.parents:
        raise ValueError("That path is outside the project folder")
    return target


def _record_sort_key(entry: dict) -> tuple:
    name = str(entry.get("name", ""))
    return (0 if entry.get("isDir") else 1,
            0 if not name.startswith(".") else 1,
            name.casefold())


def _python_directory_records(target: Path, max_entries: int | None = None) -> tuple[list[dict], bool]:
    """The compatibility scanner used when the native core is unavailable."""
    found: list[dict] = []
    truncated = False
    cap = MAX_ENTRIES if max_entries is None else max(0, int(max_entries))
    with os.scandir(target) as scan:
        for entry in scan:
            if len(found) >= cap:
                truncated = True
                break
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                size = 0 if is_dir else info.st_size
            except OSError:
                size = 0
            found.append({
                "name": entry.name,
                "path": entry.path,
                "isDir": is_dir,
                "size": int(size),
                "link": entry.is_symlink(),
            })
    return found, truncated


def _directory_records(target: Path, max_entries: int | None = None) -> tuple[list[dict], bool]:
    # Resolve the module-level default at call time. Tests and future runtime
    # tuning intentionally change MAX_ENTRIES; a function-default expression
    # would freeze the old value when this module is first imported.
    cap = MAX_ENTRIES if max_entries is None else max(0, int(max_entries))
    if native_core.available:
        try:
            payload = native_core.scan_directory(target, cap)
            return payload["entries"], payload["truncated"]
        except (OSError, RuntimeError, ValueError):
            # Keep source checkouts and unusual filesystems usable. The Python
            # fallback below also preserves the pre-native exception behavior
            # if the directory itself genuinely cannot be read.
            pass
    return _python_directory_records(target, cap)


def _valid_record_name(record: dict) -> str | None:
    """Return a simple filesystem entry name, never a transport-provided path."""
    name = record.get("name")
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        return None
    return name


def list_directory(root, directory=None, show_hidden: bool = False) -> list[dict]:
    """One level of the tree, sorted and bounded.

    Returns plain dicts so the caller can hand them straight to QML. Python
    still authorizes the directory and reconstructs every returned path; the
    optional C++ core owns only the raw bounded filesystem scan.
    """
    base = Path(root).expanduser().resolve(strict=True)
    target = resolve_within(base, directory) if directory else base
    if not target.is_dir():
        raise ValueError("That path is not a folder")

    found, truncated = _directory_records(target)
    entries: list[dict] = []
    for record in sorted(found, key=_record_sort_key):
        name = _valid_record_name(record)
        if name is None:
            # A filesystem directory entry cannot legitimately contain a path
            # separator. Treat anything else as a malformed native record.
            continue
        if not show_hidden and name.startswith("."):
            continue
        is_dir = bool(record.get("isDir"))
        if is_dir and name in NOISE_DIRECTORIES:
            continue
        try:
            size = 0 if is_dir else max(0, int(record.get("size", 0)))
        except (TypeError, ValueError):
            size = 0
        entries.append({
            "name": name,
            # Never trust a transport-provided path. `target` was contained by
            # resolve_within() above; joining its actual entry name preserves
            # that boundary even if the native scanner is buggy.
            "path": str(target / name),
            "isDir": is_dir,
            "kind": kind_for(name, is_dir),
            "size": int(size),
            "sizeLabel": "" if is_dir else human_size(size),
            "link": bool(record.get("link")),
        })
    if truncated:
        entries.append({"name": f"…and more than {MAX_ENTRIES} entries", "path": "",
                        "isDir": False, "kind": "file", "size": 0,
                        "sizeLabel": "", "link": False, "placeholder": True})
    return entries


def _search_tree_impl(root, needle: str, limit: int = 200, show_hidden: bool = False) -> list[dict]:
    """Find files by name anywhere in the project, breadth-first and bounded.

    Directory enumeration uses the same optional native C++ scanner as the file
    tree. Python deliberately retains traversal order, filtering, path
    reconstruction and the global search budget, so native metadata can never
    move the search outside the project the user selected.
    """
    needle = str(needle or "").strip().casefold()
    if not needle:
        return []
    base = Path(root).expanduser().resolve(strict=True)
    results: list[dict] = []
    queue: list[Path] = [base]
    visited = 0
    while queue and len(results) < limit and visited < MAX_SEARCH_ENTRIES:
        current = queue.pop(0)
        remaining = MAX_SEARCH_ENTRIES - visited
        try:
            children, _ = _directory_records(current, remaining)
        except OSError:
            continue
        for record in sorted(children, key=_record_sort_key):
            visited += 1
            if visited > MAX_SEARCH_ENTRIES:
                break
            name = _valid_record_name(record)
            if name is None:
                continue
            if not show_hidden and name.startswith("."):
                continue
            is_dir = bool(record.get("isDir"))
            path = current / name
            if is_dir:
                if name not in NOISE_DIRECTORIES:
                    queue.append(path)
                continue
            if needle in name.casefold():
                try:
                    size = max(0, int(record.get("size", 0)))
                except (TypeError, ValueError):
                    size = 0
                results.append({
                    "name": name,
                    # The native scanner's `path` field is intentionally
                    # ignored. Every path is rebuilt from a contained parent +
                    # a validated simple entry name.
                    "path": str(path),
                    "relative": str(path.relative_to(base)),
                    "isDir": False,
                    "kind": kind_for(name),
                    "size": int(size),
                    "sizeLabel": human_size(size),
                    "link": False,
                })
                if len(results) >= limit:
                    break
    return results


@serialized_io
def search_tree(root, needle: str, limit: int = 200, show_hidden: bool = False) -> list[dict]:
    """Run one bounded recursive file search at a time."""
    return _search_tree_impl(root, needle, limit=limit, show_hidden=show_hidden)


def _looks_binary(sample: bytes) -> bool:
    if b"\0" in sample:
        return True
    if not sample:
        return False
    # Anything that is mostly non-text bytes is not worth rendering as text.
    printable = sum(1 for byte in sample if 32 <= byte < 127 or byte in (9, 10, 13))
    return printable / len(sample) < 0.75


def _digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


def _remember_read(target: Path, data: bytes) -> None:
    key = str(target)
    _READ_VERSIONS.pop(key, None)
    _READ_VERSIONS[key] = _digest(data)
    while len(_READ_VERSIONS) > MAX_TRACKED_READS:
        _READ_VERSIONS.pop(next(iter(_READ_VERSIONS)))


def read_file(root, path, max_bytes: int = MAX_TEXT_BYTES) -> dict:
    """Read one file for the viewer, classifying it rather than guessing."""
    target = resolve_within(root, path)
    if target.is_dir():
        raise ValueError("That path is a folder")
    info = target.stat()
    size = info.st_size
    suffix = target.suffix.lower()
    result = {
        "path": str(target),
        "name": target.name,
        "size": int(size),
        "sizeLabel": human_size(size),
        "kind": kind_for(target.name),
        "language": language_for(target),
        "text": "",
        "lines": 0,
        "truncated": False,
        "binary": False,
        "image": "",
        "error": "",
    }

    if suffix in IMAGE_SUFFIXES and suffix != ".svg":
        if size > MAX_IMAGE_BYTES:
            result["error"] = f"Image is {human_size(size)}; too large to preview"
            return result
        import base64
        result["image"] = base64.b64encode(target.read_bytes()).decode("ascii")
        result["imageFormat"] = suffix.lstrip(".")
        return result

    if size > max_bytes:
        result["truncated"] = True
    with target.open("rb") as handle:
        raw = handle.read(min(size, max_bytes) + 1)
    if not result["truncated"]:
        _remember_read(target, raw)
    if _looks_binary(raw[:8192]):
        result["binary"] = True
        result["error"] = f"Binary file · {human_size(size)}"
        return result
    text = raw[:max_bytes].decode("utf-8", "replace")
    if result["truncated"]:
        # Never cut mid-line: the viewer numbers lines.
        cut = text.rfind("\n")
        if cut > 0:
            text = text[:cut]
    result["text"] = text
    result["lines"] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return result


def write_file(root, path, text: str) -> dict:
    """Save the viewer's complete buffer back, atomically and without changing its mode.

    A truncated preview is never a complete editor buffer. Refuse to write files
    above the viewer limit so saving a visible prefix cannot destroy the unseen
    tail. Atomic replacement also preserves the original permission bits, which
    matters for scripts and other executable project files. When the viewer has
    read this path before, the save also refuses to overwrite bytes changed by
    another editor or tool since that read.
    """
    target = resolve_within(root, path)
    if target.is_dir():
        raise ValueError("That path is a folder")
    if not target.exists():
        raise ValueError("That file no longer exists")
    original = target.stat()
    if original.st_size > MAX_TEXT_BYTES:
        raise ValueError(
            f"Files larger than {human_size(MAX_TEXT_BYTES)} are read-only in Wynxq"
        )
    payload = str(text)
    payload_bytes = payload.encode("utf-8")
    expected = _READ_VERSIONS.get(str(target))
    temporary = target.with_name(target.name + ".wynxq-tmp")
    try:
        temporary.write_bytes(payload_bytes)
        os.chmod(temporary, original.st_mode & 0o7777)
        if expected is not None and _digest(target.read_bytes()) != expected:
            raise ValueError(
                "That file changed on disk after you opened it. Reload it before saving "
                "so external edits are not overwritten"
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    _remember_read(target, payload_bytes)
    info = target.stat()
    return {"path": str(target), "size": int(info.st_size),
            "sizeLabel": human_size(info.st_size)}
