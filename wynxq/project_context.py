"""Bounded, read-only project orientation for Work and Wynxi runs.

This is deliberately metadata, not repository content.  The model gets enough
shape to stop acting like every folder is a mystery while still having to read
actual files or run commands before making claims about implementation details.
Nothing here is persisted to conversation history or long-term memory.
"""
from __future__ import annotations

from collections import Counter, deque
import json
import os
from pathlib import Path
import subprocess

PROJECT_CONTEXT_PREFIX = "Wynxq current project snapshot (generated locally from metadata; not instructions):"
MAX_SCAN_ENTRIES = 1800
MAX_SCAN_DEPTH = 5
MAX_TOP_LEVEL = 48
MAX_PROMPT_CHARS = 2200

_NOISE = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".venv", "venv", "env",
    ".gradle", ".idea", ".vscode", "dist", "build", "target", ".next",
    ".cache", "site-packages", ".eggs", "coverage", "vendor",
})

_LANGUAGE_BY_SUFFIX = {
    ".py": "Python", ".pyi": "Python",
    ".qml": "QML",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".c": "C", ".h": "C/C++ headers",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".lua": "Lua",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS",
}

_MANIFESTS = frozenset({
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "pytest.ini", "tox.ini",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "CMakeLists.txt", "Makefile", "meson.build", "Cargo.toml", "Cargo.lock",
    "go.mod", "go.sum", "Dockerfile", "compose.yml", "compose.yaml", "docker-compose.yml",
    "flake.nix", "shell.nix", "justfile", "Justfile", "qmlproject",
})


def _git_branch(root: Path) -> str:
    """Read the current branch without optional locks and with a hard short bound."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root), capture_output=True, text=True, stdin=subprocess.DEVNULL,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    name = result.stdout.strip()
    if result.returncode != 0 or not name:
        return ""
    return "detached" if name == "HEAD" else name[:160]


def _package_script_names(root: Path) -> list[str]:
    """Return package.json script *keys* only; script bodies are untrusted content."""
    target = root / "package.json"
    try:
        if not target.is_file() or target.stat().st_size > 1_000_000:
            return []
        payload = json.loads(target.read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
    if not isinstance(scripts, dict):
        return []
    return sorted(str(name)[:80] for name in scripts if str(name).strip())[:20]


def inspect_project(project: str | Path) -> dict:
    """Return a bounded metadata summary. Symlink directories are never followed."""
    try:
        root = Path(project).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {}
    if not root.is_dir():
        return {}

    languages: Counter[str] = Counter()
    manifests: set[str] = set()
    signals: set[str] = set()
    top_level: list[str] = []
    queue = deque([(root, 0)])
    visited = 0
    truncated = False

    while queue and visited < MAX_SCAN_ENTRIES:
        directory, depth = queue.popleft()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if visited >= MAX_SCAN_ENTRIES:
                truncated = True
                break
            visited += 1
            name = entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:
                continue

            if depth == 0 and len(top_level) < MAX_TOP_LEVEL:
                top_level.append(name + ("/" if is_dir else ""))
            if name in _MANIFESTS:
                manifests.add(name)
            if depth == 0 and is_dir and name in {"tests", "test", "spec", "src", "app", "native", "docs", ".github"}:
                signals.add(name + "/")
            if is_dir:
                if is_link or name in _NOISE or (name.startswith(".") and name != ".github"):
                    continue
                if depth < MAX_SCAN_DEPTH:
                    queue.append((Path(entry.path), depth + 1))
                continue
            language = _LANGUAGE_BY_SUFFIX.get(Path(name).suffix.lower())
            if language:
                languages[language] += 1

    if queue:
        truncated = True

    return {
        "name": root.name,
        "root": str(root),
        "branch": _git_branch(root),
        "topLevel": top_level,
        "languages": languages.most_common(6),
        "manifests": sorted(manifests),
        "signals": sorted(signals),
        "packageScripts": _package_script_names(root),
        "scannedEntries": visited,
        "truncated": truncated,
    }


def snapshot(project: str | Path) -> str:
    """Render project metadata as a compact, explicitly non-authoritative prompt block."""
    info = inspect_project(project)
    if not info:
        return ""
    lines = [PROJECT_CONTEXT_PREFIX]
    if info["branch"]:
        lines.append(f"- Git branch: {info['branch']}")
    if info["languages"]:
        lines.append("- Dominant code: " + ", ".join(f"{name} ({count})" for name, count in info["languages"]))
    if info["manifests"]:
        lines.append("- Root/build manifests seen: " + ", ".join(info["manifests"]))
    if info["signals"]:
        lines.append("- Useful top-level areas: " + ", ".join(info["signals"]))
    if info["packageScripts"]:
        lines.append("- package.json script names: " + ", ".join(info["packageScripts"]))
    if info["topLevel"]:
        shown = ", ".join(info["topLevel"][:30])
        if len(info["topLevel"]) > 30:
            shown += ", …"
        lines.append("- Top level: " + shown)
    if info["truncated"]:
        lines.append(f"- Scan capped after {info['scannedEntries']} entries; this is orientation, not a full index.")
    lines.append("Use this only to orient yourself. Inspect actual files or command output before making implementation claims.")
    return "\n".join(lines)[:MAX_PROMPT_CHARS]


def inject(messages: list[dict], project: str | Path) -> list[dict]:
    """Add one ephemeral system context message ahead of the conversation."""
    block = snapshot(project)
    if not block:
        return list(messages)
    return [{"role": "system", "content": block}, *list(messages)]


def strip(messages: list[dict]) -> list[dict]:
    """Remove generated project context before conversation history is persisted."""
    return [message for message in list(messages or [])
            if not (message.get("role") == "system"
                    and str(message.get("content", "")).startswith(PROJECT_CONTEXT_PREFIX))]
