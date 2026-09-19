# Wynxq native core

Wynxq is moving toward a C++-first desktop core without throwing away the parts
of the current Python/QML application that already work well.

## Language boundaries

- **C++20** — native core and performance/safety-sensitive desktop services.
  The current core owns permission policy plus bounded read-only directory
  enumeration used by the project tree and recursive filename search. Diff
  work, PTY/process control, system telemetry, and other hot paths are
  candidates to follow when their interfaces are stable.
- **QML** — the desktop UI, layout, state presentation, accessibility, and
  interaction animation. Permanent application surfaces stay solid; glass is
  interaction feedback, not the visual foundation of the whole app.
- **JavaScript in QML** — small presentation helpers only. Business rules do
  not live in anonymous QML JavaScript functions when C++ or Python can own a
  testable implementation.
- **Python** — Ollama orchestration, higher-level agent flow, product policy,
  path containment, and migration glue while native services replace mature
  boundaries one at a time.
- **Rust** — deliberately not a baseline dependency. Add it only for an
  isolated subsystem where Rust gives a concrete reliability/security win
  large enough to justify a second native toolchain and FFI boundary.

## Current native boundaries

### Permission policy

The native policy normalizes permission modes and decides whether a desktop or
command action requires confirmation. Python retains a compatible fallback so a
source checkout can still run when the shared library is unavailable.

### Project directory scanner

The scanner owns only raw, bounded filesystem enumeration. It returns entry
metadata such as name, directory/symlink state, and size. It deliberately does
**not** decide which project paths are authorized and it never writes files.

Python validates the selected project root before scanning, filters hidden and
noise directories, controls recursive traversal budgets, and reconstructs every
UI path from a trusted parent plus a validated simple entry name. The native
`path` field is treated as untrusted transport metadata and is ignored by the
project browser/search. If native scanning fails, the same boundary falls back
to `os.scandir`.

This split is intentional: filesystem I/O moves to C++ while the existing,
well-tested containment and product rules remain in one Python layer.

## Why a C ABI

`include/wynxq/native_core.h` is intentionally a tiny C ABI over the C++ core.
That keeps the boundary stable and lets the current Python application use it
through `ctypes` without pybind11. It also leaves the door open to a future Qt
C++ application shell, Rust components, or standalone tests without binding the
core to one language runtime.

No public function transfers heap ownership. Stable literal results such as the
version are owned by the library. Directory-scan JSON and the last-error string
are thread-local library storage and remain valid until the next relevant call
on that thread. Boolean results use integer 0/1.

## Build and test

```bash
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure
```

To test the Python bridge from a source checkout:

```bash
WYNXQ_NATIVE_CORE="$PWD/build/native/libwynxq_native_core.so" python3 - <<'PY'
from pathlib import Path
from wynxq.native_core import native_core

assert native_core.available, native_core.error
print(native_core.version)
print(native_core.normalize_permission_mode("safe_auto"))
print(native_core.scan_directory(Path.cwd(), 16))
PY
```

The same configure/build/test/FFI sequence runs in GitHub Actions. The installer
release-snapshot job also builds a wheel and verifies the shared library is
actually packaged inside `wynxq/native/`.

## Migration rule

Do not rewrite a working subsystem only to increase the C++ line count. Move a
boundary when at least one of these is true:

1. it is security-critical and benefits from one canonical implementation;
2. it is CPU/IO hot enough that Python overhead is measurable;
3. it needs native OS primitives or deterministic lifetime management;
4. keeping duplicate Python/QML implementations is causing correctness bugs.

Each migrated subsystem must have tests at the native boundary before the
Python implementation is removed or reduced. Product/security policy stays on
the side of the boundary where it can be expressed once and tested clearly.
