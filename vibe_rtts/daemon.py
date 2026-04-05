import os
import socket

from PySide6.QtCore import QObject, Signal, QProcess, QTimer, QProcessEnvironment

from vibe_rtts.config import (
    PYTHON_PATH, DAEMON_SCRIPT, SOCKET_PATH,
    DAEMON_MODEL, DAEMON_DEVICE, DAEMON_COMPUTE_TYPE,
    get_nvidia_ld_path,
)


class DaemonManager(QObject):
    engine_ready = Signal()
    engine_stopped = Signal()
    engine_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._adopted = False  # True if we connected to an externally-started daemon

        # Health check timer
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(10_000)
        self._health_timer.timeout.connect(self._health_check)

    def is_running(self) -> bool:
        if self._adopted:
            return self._check_socket()
        return self._process is not None and self._process.state() == QProcess.ProcessState.Running

    def start(self):
        # Check if daemon is already running externally
        if self._check_socket():
            self._adopted = True
            self._health_timer.start()
            self.engine_ready.emit()
            return

        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self.engine_ready.emit()
            return

        self._process = QProcess(self)
        self._process.setProgram(str(PYTHON_PATH))
        self._process.setArguments([
            str(DAEMON_SCRIPT),
            "-m", DAEMON_MODEL,
            "-d", DAEMON_DEVICE,
            "-c", DAEMON_COMPUTE_TYPE,
        ])

        # Set environment with NVIDIA libs
        env = QProcessEnvironment.systemEnvironment()
        nvidia_path = get_nvidia_ld_path()
        existing = env.value("LD_LIBRARY_PATH", "")
        if nvidia_path:
            env.insert("LD_LIBRARY_PATH",
                        f"{nvidia_path}:{existing}" if existing else nvidia_path)
        self._process.setProcessEnvironment(env)

        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        self._process.start()

    def stop(self):
        self._health_timer.stop()

        if self._adopted:
            self._adopted = False
            self.engine_stopped.emit()
            return

        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.terminate()
            if not self._process.waitForFinished(5000):
                self._process.kill()
                self._process.waitForFinished(2000)

        # Clean up socket
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink(missing_ok=True)

        self._process = None
        self.engine_stopped.emit()

    def _on_stdout(self):
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode()
        if "Model loaded. Ready." in data:
            self._health_timer.start()
            self.engine_ready.emit()

    def _on_process_finished(self, exit_code, exit_status):
        self._health_timer.stop()
        self._process = None
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink(missing_ok=True)
        self.engine_stopped.emit()

    def _on_process_error(self, error):
        self._health_timer.stop()
        self.engine_error.emit(f"Daemon process error: {error}")
        self._process = None

    def _check_socket(self) -> bool:
        if not SOCKET_PATH.exists():
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(SOCKET_PATH))
            sock.sendall(b"status\n")
            resp = sock.recv(1024).decode().strip()
            sock.close()
            return resp == "ready"
        except Exception:
            return False

    def _health_check(self):
        if self._adopted:
            if not self._check_socket():
                self._adopted = False
                self._health_timer.stop()
                self.engine_stopped.emit()
            return

        if self._process and self._process.state() != QProcess.ProcessState.Running:
            self._health_timer.stop()
            self._process = None
            self.engine_stopped.emit()
