"""Test doubles shared by the test modules."""
import os
import socket
import threading

from PySide6.QtCore import QCoreApplication, QDeadlineTimer


class FakeDaemon:
    """Minimal stand-in for voice_daemon.py.

    Answers the control commands and transcribes any path to a canned reply, so
    both the daemon lifecycle tests and the transcription tests can use it.
    """

    REPLY = "pt:hello from the fake daemon"

    def __init__(self, socket_path, device="cuda", honor_shutdown=True):
        self.path = str(socket_path)
        self.device = device
        self.honor_shutdown = honor_shutdown
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        self._server.listen(4)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            try:
                cmd = conn.recv(4096).decode().strip()
                if cmd == "status":
                    conn.sendall(b"ready\n")
                elif cmd == "device":
                    conn.sendall(f"{self.device}\n".encode())
                elif cmd == "shutdown":
                    conn.sendall(b"bye\n")
                    conn.close()
                    if self.honor_shutdown:
                        self.close()
                        return
                    continue
                else:  # anything else is treated as an audio path
                    conn.sendall(f"{self.REPLY}\n".encode())
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        self._running = False
        self._server.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


def pump_until(condition, timeout_ms: int = 5000) -> bool:
    """Run the Qt event loop until `condition()` holds (or we give up).

    Tests need this because everything in the app is driven by signals from
    QProcess/QThread, which only arrive while events are being processed.
    """
    deadline = QDeadlineTimer(timeout_ms)
    while not condition():
        if deadline.hasExpired():
            return False
        QCoreApplication.processEvents()
    return True
