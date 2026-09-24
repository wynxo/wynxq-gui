# Changelog

## 1.0.0

First stable release of Wynxq — a local Ollama-powered AI workbench for Linux.

- **Three-column layout** — conversation pane, contextual dock (files, terminal, browser), and inspector.
- **Local Ollama integration** — streams responses from a self-hosted Ollama instance; no cloud dependency.
- **Desktop control** — reads and drives the desktop via `dbus-next`, with native back-ends for **Wayland** (portal) and **X11** (python-xlib).
- **Memory system** — persistent per-project memory so the assistant recalls prior decisions and context across sessions.
- **Browser, terminal, and Git panels** — in-app Chromium-style browser, embedded terminal, and Git-aware file tree with diff views.
- **Native C++ core** — `libwynxq_native_core` handles permission classification, destructive-command detection, and directory scanning; Python fallback keeps source installs usable without a compiler.
- **Installer and uninstaller** — `install.py` / `uninstall.py` manage user-local deployment, desktop entry, and icon.
- **Screenshot rendering** — offscreen Qt pipeline (`QT_QPA_PLATFORM=offscreen`) produces README screenshots in CI without a display.
