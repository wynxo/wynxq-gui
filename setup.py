"""Setuptools hook that embeds Wynxq's C++ core in Linux wheels.

The native layer is intentionally optional for source installs so a missing
compiler never makes the Python/QML fallback unusable. Release/CI builds set
WYNXQ_REQUIRE_NATIVE=1 and therefore fail if the native library cannot be
produced.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py


ROOT = Path(__file__).resolve().parent
REQUIRE_NATIVE = os.environ.get("WYNXQ_REQUIRE_NATIVE", "").strip().lower() in {
    "1", "true", "yes", "on"
}


def _native_filename() -> str:
    if os.name == "nt":
        return "wynxq_native_core.dll"
    if sys.platform == "darwin":
        return "libwynxq_native_core.dylib"
    return "libwynxq_native_core.so"


def _build_native(destination: Path) -> bool:
    source = ROOT / "native"
    cmake = shutil.which("cmake")
    if not source.is_dir() or not cmake:
        if REQUIRE_NATIVE:
            missing = "native/" if not source.is_dir() else "cmake"
            raise RuntimeError(f"Wynxq native core is required but {missing} is unavailable")
        print("warning: CMake unavailable; installing Wynxq with the Python policy fallback")
        return False

    build = ROOT / "build" / "setuptools-native"
    configure = [
        cmake, "-S", str(source), "-B", str(build),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DWYNXQ_NATIVE_BUILD_TESTS=OFF",
    ]
    try:
        subprocess.run(configure, check=True)
        subprocess.run([cmake, "--build", str(build), "--config", "Release", "--parallel", "2"],
                       check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        if REQUIRE_NATIVE:
            raise RuntimeError("Wynxq's required C++ native core failed to build") from exc
        print(f"warning: native core build failed; using Python fallback ({exc})")
        return False

    filename = _native_filename()
    candidates = [path for path in build.rglob(filename) if path.is_file()]
    if not candidates:
        if REQUIRE_NATIVE:
            raise RuntimeError(f"CMake completed but {filename} was not produced")
        print("warning: native core output was not found; using Python fallback")
        return False

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], destination / filename)
    print(f"embedded Wynxq native core: {filename}")
    return True


class NativeBuildPy(build_py):
    def run(self):
        super().run()
        _build_native(Path(self.build_lib) / "wynxq" / "native")


class BinaryDistribution(Distribution):
    """Mark wheels as platform-specific because they may contain the C++ core."""

    def has_ext_modules(self):
        return True


setup(
    cmdclass={"build_py": NativeBuildPy},
    distclass=BinaryDistribution,
)
