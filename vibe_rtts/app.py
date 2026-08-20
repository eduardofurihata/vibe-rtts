import atexit
import signal
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtDBus import QDBusConnection

from vibe_rtts.config import APP_NAME, APP_DISPLAY_NAME, DBUS_SERVICE, AUTO_START_ENGINE


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setDesktopFileName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Single instance check via DBus
    bus = QDBusConnection.sessionBus()
    if not bus.registerService(DBUS_SERVICE):
        print(f"{APP_NAME} is already running.", file=sys.stderr)
        sys.exit(0)

    # Create all components
    from vibe_rtts.tray import TrayManager
    from vibe_rtts.daemon import DaemonManager
    from vibe_rtts.recorder import RecordingEngine
    from vibe_rtts.transcriber import TranscribeWorker
    from vibe_rtts.shortcut import ShortcutHandler
    from vibe_rtts.history import HistoryStore
    from vibe_rtts.history_window import HistoryWindow

    daemon_manager = DaemonManager()
    recorder = RecordingEngine()
    shortcut_handler = ShortcutHandler()
    history_store = HistoryStore()
    history_window = HistoryWindow(history_store)

    tray = TrayManager()
    tray.init_components(
        daemon_manager=daemon_manager,
        recorder=recorder,
        transcriber_cls=TranscribeWorker,
        shortcut_handler=shortcut_handler,
        history_store=history_store,
        history_window=history_window,
    )
    tray.show()

    # Preload the model so we open in READY instead of waiting for a click.
    # Deferred to the first event loop tick on purpose: DaemonManager.start()
    # probes the socket with a 2s timeout, which would otherwise hold up the
    # tray icon whenever a stale socket is lying around.
    if AUTO_START_ENGINE:
        QTimer.singleShot(0, tray.start_engine)

    # Cleanup: unregister shortcuts so numpad keys return to normal.
    # Must run on normal exit, tray Quit, SIGTERM, and SIGINT.
    _cleaned = False

    def cleanup():
        nonlocal _cleaned
        if _cleaned:
            return
        _cleaned = True
        shortcut_handler.cleanup()
        if daemon_manager.is_running():
            daemon_manager.stop()

    atexit.register(cleanup)
    app.aboutToQuit.connect(cleanup)

    # SIGTERM/SIGINT: run cleanup then exit (atexit won't fire on raw signals)
    def _signal_handler(signum, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Qt's event loop runs in C++, so a Python signal handler only fires once the
    # interpreter gets control back. Without this idle tick, a SIGTERM (logout,
    # systemctl) sits pending and the engine keeps holding the GPU memory.
    _signal_tick = QTimer()
    _signal_tick.setInterval(200)
    _signal_tick.timeout.connect(lambda: None)
    _signal_tick.start()

    sys.exit(app.exec())
