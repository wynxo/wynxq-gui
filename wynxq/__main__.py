"""Native desktop entry point: python -m wynxq."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

UI = Path(__file__).parent / "ui"
SOCKET = "wynxq-single-instance"


def _load_fonts(app):
    """Register the bundled Inter and JetBrains Mono faces."""
    from PySide6.QtGui import QFontDatabase
    loaded = []
    for path in sorted((UI / "fonts").glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) != -1:
            loaded.append(path.name)
    return loaded


def _existing_instance(message: str) -> bool:
    """Hand a request to an already-running Wynxq, if there is one."""
    from PySide6.QtNetwork import QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer(SOCKET)
    if not socket.waitForConnected(300):
        return False
    socket.write(message.encode("utf-8"))
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def _serve_instance(controller):
    """Listen for `wynxq --quick` from another process and raise the bar."""
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(SOCKET)
    server = QLocalServer()
    if not server.listen(SOCKET):
        return None

    def accept():
        connection = server.nextPendingConnection()
        if connection is None:
            return

        def read():
            payload = bytes(connection.readAll()).decode("utf-8", "replace").strip()
            if payload == "quick":
                controller.quickBarRequested.emit()
            connection.deleteLater()

        connection.readyRead.connect(read)

    server.newConnection.connect(accept)
    return server


def _build_tray(app, window, controller):
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    icon = UI / "wynxq.svg"
    tray = QSystemTrayIcon(QIcon(str(icon)) if icon.exists() else app.windowIcon(), app)
    tray.setToolTip("Wynxq — local AI workbench")
    menu = QMenu()
    show = QAction("Open Wynxq", menu)
    show.triggered.connect(lambda: (window.show(), window.raise_() if hasattr(window, "raise_") else None,
                                    window.requestActivate()))
    quick = QAction("Quick bar", menu)
    quick.triggered.connect(controller.quickBarRequested.emit)
    fresh = QAction("New task", menu)
    fresh.triggered.connect(controller.newTask)
    stop = QAction("Stop current task", menu)
    stop.triggered.connect(controller.stop)
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    for action in (show, quick, fresh, stop):
        menu.addAction(action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: controller.quickBarRequested.emit()
                           if reason == QSystemTrayIcon.Trigger else None)
    tray.show()
    tray._menu = menu
    return tray


def main():
    parser = argparse.ArgumentParser(description="Wynxq — local AI workbench")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--quick", action="store_true",
                        help="Open the floating quick bar, reusing a running Wynxq if there is one")
    parser.add_argument("--ui-preview", metavar="SCENE", nargs="?", const="conversation",
                        help="Run the interface with fixed demo state")
    parser.add_argument("--snapshot", metavar="DIR",
                        help="Render the demo scenes to PNG files in DIR and exit")
    parser.add_argument("--size", metavar="WxH",
                        help="Window size for preview and snapshot runs, e.g. 1024x720")
    parser.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(__version__)
        return 0

    if args.quick and _existing_instance("quick"):
        return 0

    from . import browser as browser_policy
    # Qt WebEngine must be initialised before the QApplication is constructed.
    # A machine without the module simply gets a Browser panel that explains
    # itself; nothing else in Wynxq depends on it.
    browser_policy.initialize()

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Wynxq")
    app.setOrganizationName("Wynxq")
    app.setApplicationDisplayName("Wynxq")
    app.setDesktopFileName("io.github.wynxo.Wynxq")
    _load_fonts(app)
    app.setFont(QFont("Inter", 10))
    icon = UI / "wynxq.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    preview = bool(args.ui_preview or args.snapshot)
    if preview:
        from .demo import DemoController
        scene = args.ui_preview or "conversation"
        controller = DemoController(scene if not args.snapshot else "conversation")
    else:
        from .product import ProductController
        controller = ProductController(autoconnect=not args.smoke_test)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(UI))
    engine.rootContext().setContextProperty("bridge", controller)
    engine.load(QUrl.fromLocalFile(str(UI / "Main.qml")))
    if not engine.rootObjects():
        controller.shutdown()
        return 1

    if args.size:
        try:
            width, height = (int(part) for part in args.size.lower().split("x", 1))
        except ValueError:
            print("--size expects WIDTHxHEIGHT, for example 1024x720", file=sys.stderr)
            return 2
        root = engine.rootObjects()[0]
        root.setWidth(max(root.property("minimumWidth") or 0, width))
        root.setHeight(max(root.property("minimumHeight") or 0, height))

    server = None
    tray = None
    if not preview and not args.smoke_test and not args.screenshot:
        server = _serve_instance(controller)
        if getattr(controller, "trayEnabled", False):
            tray = _build_tray(app, engine.rootObjects()[0], controller)
    if args.quick:
        QTimer.singleShot(120, controller.quickBarRequested.emit)

    if args.snapshot:
        from .demo import SCENES
        _snapshot(app, engine, controller, Path(args.snapshot).expanduser(), SCENES)
    elif args.screenshot:
        _park_cursor()

        def capture():
            root = engine.rootObjects()[0]
            if not root.grabWindow().save(args.screenshot):
                print("Could not save screenshot", file=sys.stderr)
                app.exit(1)
            else:
                root.close()
                QTimer.singleShot(0, app.quit)
        QTimer.singleShot(1800, capture)
    elif args.smoke_test:
        def finish_smoke():
            root = engine.rootObjects()[0]
            root.close()
            QTimer.singleShot(0, app.quit)
        QTimer.singleShot(1200, finish_smoke)

    exit_code = app.exec()
    if server is not None:
        server.close()
    if tray is not None:
        tray.hide()
    controller.shutdown()
    return exit_code


def _park_cursor():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor
    try:
        QCursor.setPos(QPoint(4, 4))
    except Exception:
        pass


def _snapshot(app, engine, controller, directory: Path, scenes):
    """Walk every scene, rebuilding demo state and grabbing the real window."""
    from PySide6.QtCore import QTimer
    from .demo import DemoController
    directory.mkdir(parents=True, exist_ok=True)
    root = engine.rootObjects()[0]
    _park_cursor()
    pending = list(scenes)
    state = {"controller": controller}

    def advance():
        if not pending:
            root.close()
            QTimer.singleShot(0, app.quit)
            return
        name, scene, overlay = pending.pop(0)
        fresh = DemoController(scene)
        engine.rootContext().setContextProperty("bridge", fresh)
        previous, state["controller"] = state["controller"], fresh
        if previous is not None:
            QTimer.singleShot(2500, previous.shutdown)
        root.setProperty("previewOverlay", "")
        QTimer.singleShot(500, lambda: apply_overlay(name, overlay))

    def apply_overlay(name, overlay):
        root.setProperty("previewOverlay", overlay)
        QTimer.singleShot(1000, lambda: capture(name))

    def capture(name):
        target = directory / f"{name}.png"
        window = root
        if root.property("previewOverlay") == "quickbar":
            floating = root.property("quickBarWindow")
            if floating is not None:
                window = floating
        if window.grabWindow().save(str(target)):
            print(f"saved {target}")
        else:
            print(f"could not save {target}", file=sys.stderr)
        QTimer.singleShot(250, advance)

    QTimer.singleShot(1400, advance)


if __name__ == "__main__":
    sys.exit(main())