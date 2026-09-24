"""Optional bridge to Wynxq's C++ native core.

The Python application remains runnable from a source checkout even when the
native library has not been built yet. Release/install tooling can place the
library beside this module, while developers can point WYNXQ_NATIVE_CORE at a
CMake build. Callers can check ``native_core.available`` before using it.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from typing import Iterable


_ENV = "WYNXQ_NATIVE_CORE"


def _library_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("wynxq_native_core.dll",)
    if sys_platform() == "darwin":
        return ("libwynxq_native_core.dylib",)
    return ("libwynxq_native_core.so",)


def sys_platform() -> str:
    # Kept tiny and injectable in tests without importing platform (which does
    # considerably more work than we need during application startup).
    import sys
    return sys.platform


def _candidate_paths() -> Iterable[Path]:
    override = os.environ.get(_ENV, "").strip()
    if override:
        yield Path(override).expanduser()

    package = Path(__file__).resolve().parent
    root = package.parent
    for name in _library_names():
        yield package / "native" / name
        yield package / name
        # Developer CMake builds; these are intentionally after packaged paths.
        yield root / "build" / "native" / name
        yield root / "build-native" / name


class NativeCore:
    """Thin, ownership-free ctypes wrapper around the stable C ABI."""

    def __init__(self) -> None:
        self._library: ctypes.CDLL | None = None
        self._path = ""
        self._error = ""
        self._load()

    @property
    def available(self) -> bool:
        return self._library is not None

    @property
    def path(self) -> str:
        return self._path

    @property
    def error(self) -> str:
        return self._error

    def _load(self) -> None:
        errors: list[str] = []
        for path in _candidate_paths():
            if not path.is_file():
                continue
            try:
                library = ctypes.CDLL(str(path))
                self._configure(library)
                # Force one ABI call now so a wrong/old library fails during
                # discovery rather than halfway through an agent action.
                version = library.wynxq_native_version()
                if not version:
                    raise RuntimeError("native core returned an empty version")
            except (OSError, AttributeError, RuntimeError) as exc:
                errors.append(f"{path}: {exc}")
                continue
            self._library = library
            self._path = str(path)
            self._error = ""
            return
        if errors:
            self._error = "; ".join(errors)
        elif os.environ.get(_ENV):
            self._error = f"{_ENV} does not point to a readable native core library"

    @staticmethod
    def _configure(library: ctypes.CDLL) -> None:
        library.wynxq_native_version.argtypes = []
        library.wynxq_native_version.restype = ctypes.c_char_p
        library.wynxq_normalize_permission_mode.argtypes = [ctypes.c_char_p]
        library.wynxq_normalize_permission_mode.restype = ctypes.c_char_p
        library.wynxq_command_is_destructive.argtypes = [ctypes.c_char_p]
        library.wynxq_command_is_destructive.restype = ctypes.c_int
        library.wynxq_permission_needs_confirmation.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        ]
        library.wynxq_permission_needs_confirmation.restype = ctypes.c_int
        library.wynxq_scan_directory_json.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        library.wynxq_scan_directory_json.restype = ctypes.c_char_p
        library.wynxq_native_last_error.argtypes = []
        library.wynxq_native_last_error.restype = ctypes.c_char_p

    def _require(self) -> ctypes.CDLL:
        if self._library is None:
            detail = f" ({self._error})" if self._error else ""
            raise RuntimeError("Wynxq native core is not available" + detail)
        return self._library

    @staticmethod
    def _bytes(value: str | None) -> bytes | None:
        return None if value is None else str(value).encode("utf-8")

    @property
    def version(self) -> str:
        value = self._require().wynxq_native_version()
        return value.decode("ascii", "strict")

    def normalize_permission_mode(self, mode: str | None) -> str:
        value = self._require().wynxq_normalize_permission_mode(self._bytes(mode))
        if not value:
            return "safe"
        return value.decode("ascii", "strict")

    def command_is_destructive(self, command: str | None) -> bool:
        return bool(self._require().wynxq_command_is_destructive(self._bytes(command)))

    def needs_confirmation(self, action: str, mode: str,
                           command: str | None = None) -> bool:
        return bool(self._require().wynxq_permission_needs_confirmation(
            self._bytes(action), self._bytes(mode), self._bytes(command)
        ))

    def scan_directory(self, directory: str | os.PathLike,
                       max_entries: int = 4000) -> dict:
        """Return raw metadata for one directory from the C++ filesystem core.

        The caller remains responsible for authorising/containing ``directory``
        and for product-specific filtering/sorting. Paths use the OS filesystem
        encoding so Linux filenames containing undecodable bytes still survive
        the FFI round-trip through surrogateescape.
        """
        library = self._require()
        limit = max(0, min(int(max_entries), 100000))
        raw = library.wynxq_scan_directory_json(
            os.fsencode(os.fspath(directory)), ctypes.c_size_t(limit)
        )
        if not raw:
            detail = library.wynxq_native_last_error()
            message = os.fsdecode(detail) if detail else "native directory scan failed"
            raise RuntimeError(message)
        try:
            payload = json.loads(os.fsdecode(raw))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("native directory scanner returned invalid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            raise RuntimeError("native directory scanner returned an invalid payload")
        if not isinstance(payload.get("truncated"), bool):
            raise RuntimeError("native directory scanner omitted its truncation state")
        for entry in payload["entries"]:
            if not isinstance(entry, dict):
                raise RuntimeError("native directory scanner returned an invalid entry")
            if not isinstance(entry.get("name"), str) or not isinstance(entry.get("path"), str):
                raise RuntimeError("native directory scanner returned an invalid path")
            if not isinstance(entry.get("isDir"), bool) or not isinstance(entry.get("link"), bool):
                raise RuntimeError("native directory scanner returned invalid file flags")
            size = entry.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise RuntimeError("native directory scanner returned an invalid file size")
        return payload


native_core = NativeCore()


__all__ = ['NativeCore', 'sys_platform']
