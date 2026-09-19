"""Render deterministic live and idle token-usage states for visual QA."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from wynxq.__main__ import UI, _load_fonts
from wynxq.demo import DemoController


def metric(tokens: int, prompt: int, rate: float) -> dict:
    return {
        "tokens": tokens,
        "prompt_tokens": prompt,
        "cached_prompt_tokens": prompt // 3,
        "load_ms": 120.0,
        "total_ms": max(1000.0, tokens / max(rate, 0.1) * 1000.0),
        "tokens_per_second": rate,
    }


def main(target: str, state: str = "live") -> int:
    if state not in {"live", "idle"}:
        raise ValueError("state must be 'live' or 'idle'")

    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName(f"Wynxq token usage {state} snapshot")
    _load_fonts(app)
    app.setFont(QFont("Inter", 10))

    controller = DemoController("conversation")
    if state == "live":
        controller._usage.reset()
        controller._usage.exact_metrics(metric(45, 120, 2.5))
        controller._busy = True
        controller._status = "Writing"
    else:
        controller._usage.reset()
        controller._busy = False
        controller._status = "Ready"
    controller.usageChanged.emit()
    controller.changed.emit()

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(UI))
    engine.rootContext().setContextProperty("bridge", controller)
    engine.load(QUrl.fromLocalFile(str(UI / "Main.qml")))
    if not engine.rootObjects():
        controller.shutdown()
        return 1

    root = engine.rootObjects()[0]
    root.setWidth(1440)
    root.setHeight(920)
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"ok": False}

    def capture():
        result["ok"] = root.grabWindow().save(str(output))
        if result["ok"]:
            print(f"saved {state} token usage to {output}")
        else:
            print(f"could not save {output}", file=sys.stderr)
        root.close()
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(900, capture)
    code = app.exec()
    controller.shutdown()
    return code if code else (0 if result["ok"] else 4)


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: token_usage_snapshot.py OUTPUT.png [live|idle]")
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "live"))
