# Contributing to Wynxq

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest
```

Qt requires a platform plugin. On headless machines (CI, containers):

```bash
export QT_QPA_PLATFORM=offscreen
export QT_QUICK_BACKEND=software
```

Install system Qt runtime libraries on Debian/Ubuntu:

```bash
sudo apt-get install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0 \
  libnss3 libxcomposite1 libxdamage1 libxrandr2 libasound2t64
```

## Running Tests

```bash
QT_QPA_PLATFORM=offscreen pytest
```

Or with multiple workers:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

Some test modules (dock controller, live streaming) spin up native Qt objects
or `QCoreApplication` and are best run in isolation — see `.github/workflows/ci.yml`
for the exact CI splitting.

## Refreshing Screenshots

Screenshots are rendered with the offscreen Qt backend:

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  python -m wynxq --snapshot assets/screenshots
```

Token-usage and compact-chat snapshots:

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  python tests/token_usage_snapshot.py assets/screenshots/token-usage-live.png live
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  python tests/token_usage_snapshot.py assets/screenshots/token-usage-idle.png idle
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  python -m wynxq --ui-preview conversation --size 760x640 \
  --screenshot assets/screenshots/compact-chat.png
```

Update `README.md` screenshot table references only after verifying the rendered
output in `assets/screenshots/`.

## PR Checklist

- [ ] `QT_QPA_PLATFORM=offscreen pytest` passes locally
- [ ] Native C++ core builds: `cmake -S native -B build/native && cmake --build build/native`
- [ ] `WYNXQ_REQUIRE_NATIVE=1 pip install .` succeeds (wheel embeds `libwynxq_native_core.so`)
- [ ] Screenshots render without error: `python -m wynxq --snapshot /tmp/screenshots`
- [ ] `python -m wynxq --smoke-test` loads the GUI without crashing

## Code Style

- **Type hints:** annotate all public functions and methods.
- **`__all__` exports:** public modules declare `__all__` listing the supported API.
- **PEP 8:** 4-space indentation, 79-char line limit (soft), `isort`-style imports.
- **No formatter enforcement:** match the surrounding style; don't reformat unrelated code.

## Architecture Notes

- `wynxq/` — Python package. `__init__.py` exposes `__version__`; public surfaces use `__all__`.
- `native/` — C++17 core (CMake). Python fallback in `wynxq/native_core.py` is always available.
- `wynxq/ui/` — QML interface. PySide6 (`PySide6>=6.8`) loads it.
- `tests/` — pytest suite. `testpaths = ["tests"]` in `pyproject.toml`.
- `install.py` / `uninstall.py` — user-facing install scripts.
