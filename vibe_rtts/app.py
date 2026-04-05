import atexit
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtDBus import QDBusConnection

from vibe_rtts.config import APP_NAME, APP_DISPLAY_NAME, DBUS_SERVICE


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

    # Cleanup on exit
    def cleanup():
        shortcut_handler.cleanup()
        if daemon_manager.is_running():
            daemon_manager.stop()

    atexit.register(cleanup)

    sys.exit(app.exec())
