import atexit
import signal
import socket
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSocketNotifier, QTimer

from vibe_rtts.config import APP_NAME, APP_DISPLAY_NAME, DBUS_SERVICE, AUTO_START_ENGINE, IS_MACOS


def _claim_single_instance():
    """Return an object that holds the instance lock, or None if another one runs.

    Linux uses the DBus session bus. macOS has no session bus — registerService
    would fail every time and the app would always think it was already running —
    so there a QLocalServer plays the lock. Keep the returned object alive.
    """
    if not IS_MACOS:
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        return bus if bus.registerService(DBUS_SERVICE) else None

    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer(APP_NAME)
    if probe.waitForConnected(500):
        # Opening the app again should not look like nothing happened: ask the
        # running one to say where it is.
        probe.write(b"show\n")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return None
    # Nobody answered: any socket file left there is from a crashed run.
    QLocalServer.removeServer(APP_NAME)
    server = QLocalServer()
    return server if server.listen(APP_NAME) else None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setDesktopFileName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if IS_MACOS:
        from vibe_rtts.macos_app import hide_dock_icon
        hide_dock_icon()

    instance_lock = _claim_single_instance()
    if instance_lock is None:
        print(f"{APP_NAME} is already running.", file=sys.stderr)
        sys.exit(0)

    # Create all components
    from vibe_rtts.tray import TrayManager
    from vibe_rtts.daemon import DaemonManager
    from vibe_rtts.recorder import RecordingEngine
    from vibe_rtts.transcriber import TranscribeWorker
    if IS_MACOS:
        from vibe_rtts.shortcut_macos import MacShortcutHandler as ShortcutHandler
    else:
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

    if IS_MACOS:
        def _on_another_launch():
            conn = instance_lock.nextPendingConnection()
            if conn is None:
                return
            conn.disconnected.connect(conn.deleteLater)
            print(f"[{APP_NAME}] Opened again while running; showing where we are.", flush=True)
            tray.showMessage(APP_DISPLAY_NAME,
                             "Already running — look for the mic in the menu bar.")

        instance_lock.newConnection.connect(_on_another_launch)

    # Preload the model so we open in READY instead of waiting for a click.
    # Deferred to the first event loop tick on purpose: DaemonManager.start()
    # probes the socket with a 2s timeout, which would otherwise hold up the
    # tray icon whenever a stale socket is lying around.
    if AUTO_START_ENGINE:
        QTimer.singleShot(0, tray.start_engine)

    # Cleanup: unregister shortcuts so the keys return to normal.
    # Must run on normal exit, tray Quit, SIGTERM, and SIGINT.
    _cleaned = False

    def cleanup():
        nonlocal _cleaned
        if _cleaned:
            return
        _cleaned = True
        recorder.abort()
        tray.wait_for_transcription()
        shortcut_handler.cleanup()
        if daemon_manager.is_running():
            daemon_manager.stop()

    atexit.register(cleanup)
    app.aboutToQuit.connect(cleanup)

    # SIGTERM/SIGINT (logout, systemctl, Ctrl+C) must free the GPU, and Qt's event
    # loop runs in C++ — a Python handler would only fire once the interpreter got
    # control back. set_wakeup_fd has the C-level handler write a byte, which wakes
    # the loop through this notifier; no timer polling for nothing.
    #
    # The handler itself does nothing on purpose. Running cleanup() and sys.exit()
    # inside it means unwinding through PySide's slot dispatch, which segfaults —
    # so the notifier asks Qt for an orderly quit and aboutToQuit runs cleanup at
    # a safe point.
    wake_w, wake_r = socket.socketpair()
    wake_w.setblocking(False)
    wake_r.setblocking(False)
    signal.set_wakeup_fd(wake_w.fileno())
    signal_notifier = QSocketNotifier(wake_r.fileno(), QSocketNotifier.Type.Read)

    def _on_signal_wakeup():
        try:
            wake_r.recv(1024)
        except BlockingIOError:
            pass
        print(f"[{APP_NAME}] Signal received, shutting down.", flush=True)
        app.quit()

    signal_notifier.activated.connect(lambda *_: _on_signal_wakeup())
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.signal(signal.SIGINT, lambda *_: None)

    sys.exit(app.exec())
