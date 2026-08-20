import os
import socket
import subprocess
import time

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
        self.device = None     # Device the running model is on ("cuda"/"cpu"/None)
        self._stopping = False  # True while we kill the daemon on purpose
        self._stderr_tail = []  # Last stderr lines, to report why the daemon died

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
            # Refuse to adopt a CPU daemon: large-v3 on CPU is too slow to be usable,
            # and it would sit on READY looking fine. Older daemons don't know the
            # "device" command — treat their answer as unknown and adopt anyway.
            device = self._ask("device")
            if device == "cpu":
                self.engine_error.emit(
                    "A daemon is already running on CPU (too slow to use). "
                    "Stop it and start the engine again."
                )
                return
            self.device = device if device in ("cuda", "cpu") else None
            self._adopted = True
            self._health_timer.start()
            self.engine_ready.emit()
            return

        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self.engine_ready.emit()
            return

        self._stderr_tail = []
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
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        self._process.start()

    def stop(self):
        self._health_timer.stop()
        self._stopping = True

        if self._adopted:
            self._adopted = False
            self.device = None
            self._kill_external_daemon()
            self._stopping = False
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
        self.device = None
        self._stopping = False
        self.engine_stopped.emit()

    def _on_stdout(self):
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode()
        print(f"[DAEMON] {data.rstrip()}", flush=True)
        if "Model loaded. Ready." in data:
            self.device = DAEMON_DEVICE  # no CPU fallback: it died or it is on DAEMON_DEVICE
            self._health_timer.start()
            self.engine_ready.emit()

    def _on_stderr(self):
        if not self._process:
            return
        data = self._process.readAllStandardError().data().decode(errors="replace")
        print(f"[DAEMON] {data.rstrip()}", flush=True)
        self._stderr_tail.extend(line for line in data.splitlines() if line.strip())
        del self._stderr_tail[:-5]

    def _on_process_finished(self, exit_code, exit_status):
        self._health_timer.stop()
        self._process = None
        self.device = None
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink(missing_ok=True)
        # A crash (e.g. no VRAM left) must be visible: emitting engine_stopped alone
        # would send the tray back to INACTIVE with no explanation.
        if exit_code != 0 and not self._stopping:
            reason = " ".join(self._stderr_tail).strip() or f"exit code {exit_code}"
            self.engine_error.emit(reason)
            return
        self._stopping = False
        self.engine_stopped.emit()

    def _on_process_error(self, error):
        self._health_timer.stop()
        if not self._stopping:
            self.engine_error.emit(f"Daemon process error: {error}")
        self._process = None

    def _ask(self, command: str) -> str | None:
        """Send one command to the daemon socket, return its reply (None on failure)."""
        if not SOCKET_PATH.exists():
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(SOCKET_PATH))
            sock.sendall(f"{command}\n".encode())
            resp = sock.recv(1024).decode().strip()
            sock.close()
            return resp
        except Exception:
            return None

    def _check_socket(self) -> bool:
        return self._ask("status") == "ready"

    def _kill_external_daemon(self):
        """Free the GPU memory of a daemon we adopted (we have no QProcess for it).

        Ask it to exit over the socket first; that works for any of our daemons and
        needs no PID. If it will not go, SIGTERM/SIGKILL the process running our
        daemon script — never an unrelated one on the same socket.
        """
        if not SOCKET_PATH.exists():
            return

        self._ask("shutdown")
        for _ in range(30):  # ~3s for the model to be torn down
            if not SOCKET_PATH.exists():
                return
            time.sleep(0.1)

        pids = self._find_daemon_pids()
        if not pids:
            self.engine_error.emit(
                "An external transcription daemon is still holding the GPU memory "
                "and would not shut down. Stop it manually to free the VRAM."
            )
            return

        for sig in ("-TERM", "-KILL"):
            for pid in pids:
                subprocess.run(["kill", sig, pid], capture_output=True)
            for _ in range(20):  # ~2s
                if not self._find_daemon_pids():
                    SOCKET_PATH.unlink(missing_ok=True)
                    return
                time.sleep(0.1)
        self.engine_error.emit("Could not kill the transcription daemon; VRAM may stay in use.")

    def _find_daemon_pids(self) -> list[str]:
        """PIDs running our daemon script, so we never kill someone else's process."""
        try:
            out = subprocess.run(["pgrep", "-f", str(DAEMON_SCRIPT)],
                                 capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return []
        mine = str(os.getpid())
        return [p for p in out.split() if p and p != mine]

    def _health_check(self):
        if self._adopted:
            if not self._check_socket():
                self._adopted = False
                self.device = None
                self._health_timer.stop()
                self.engine_stopped.emit()
            return

        if self._process and self._process.state() != QProcess.ProcessState.Running:
            self._health_timer.stop()
            self._process = None
            self.device = None
            self.engine_stopped.emit()
