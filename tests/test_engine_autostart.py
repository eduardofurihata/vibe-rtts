"""Tests for the startup preload (config.AUTO_START_ENGINE) and for stopping a
daemon we adopted instead of spawned."""
import os
import socket
import sys
import threading
import time

# Add project root to path so vibe_rtts can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

from vibe_rtts.tray import TrayManager, AppState
from vibe_rtts.daemon import DaemonManager

# Need a QApplication instance for Qt widgets
app = QApplication.instance() or QApplication([])


class TestStartEngine:
    """start_engine() loads the model without recording, from INACTIVE only."""

    def _make_tray(self):
        tray = TrayManager()
        tray.daemon_manager = MagicMock()
        tray.recorder = MagicMock()
        return tray

    def test_start_engine_from_inactive_loads_model(self):
        tray = self._make_tray()
        tray.start_engine()
        assert tray._state == AppState.LOADING
        tray.daemon_manager.start.assert_called_once()

    def test_start_engine_does_not_record(self):
        """The preload must not start recording once the model is ready."""
        tray = self._make_tray()
        tray.start_engine()
        assert tray._pending_record_after_load is False
        tray._on_engine_ready()
        assert tray._state == AppState.READY
        tray.recorder.start_recording.assert_not_called()

    def test_start_engine_is_noop_when_not_inactive(self):
        tray = self._make_tray()
        for state in (AppState.LOADING, AppState.READY,
                      AppState.RECORDING, AppState.TRANSCRIBING):
            tray._state = state
            tray.daemon_manager.reset_mock()
            tray.start_engine()
            assert tray._state == state
            tray.daemon_manager.start.assert_not_called()

    def test_menu_toggle_still_starts_and_stops(self):
        tray = self._make_tray()
        tray._on_engine_toggle()
        assert tray._state == AppState.LOADING
        tray.daemon_manager.start.assert_called_once()

        tray._on_engine_ready()
        tray._on_engine_toggle()
        tray.daemon_manager.stop.assert_called_once()

    def test_ready_tooltip_warns_about_cpu(self):
        tray = self._make_tray()
        tray.daemon_manager.device = "cpu"
        tray._update_state(AppState.READY)
        assert "CPU" in tray.toolTip()

        tray._state = AppState.INACTIVE
        tray.daemon_manager.device = "cuda"
        tray._update_state(AppState.READY)
        assert "CPU" not in tray.toolTip()


class FakeDaemon:
    """Minimal stand-in for voice_daemon.py: answers status/device/shutdown."""

    def __init__(self, socket_path, device="cuda", honor_shutdown=True):
        self.path = str(socket_path)
        self.device = device
        self.honor_shutdown = honor_shutdown
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        self._server.listen(2)
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
                else:
                    conn.sendall(b"ERROR: file not found\n")
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


class TestAdoptedDaemon:
    """Adoption must check the device, and Stop must actually free the VRAM."""

    def test_stop_shuts_down_adopted_daemon(self, tmp_path):
        sock_path = tmp_path / "voice-daemon.sock"
        daemon = FakeDaemon(sock_path)
        try:
            with patch("vibe_rtts.daemon.SOCKET_PATH", sock_path):
                mgr = DaemonManager()
                ready = MagicMock()
                stopped = MagicMock()
                mgr.engine_ready.connect(ready)
                mgr.engine_stopped.connect(stopped)

                mgr.start()
                ready.assert_called_once()
                assert mgr._adopted is True
                assert mgr.device == "cuda"

                mgr.stop()
                stopped.assert_called_once()
                # The daemon is gone, not just forgotten: that is the VRAM being freed
                assert not sock_path.exists()
                assert mgr.device is None
        finally:
            daemon.close()

    def test_stop_reports_daemon_that_refuses_to_die(self, tmp_path):
        """An external daemon we cannot kill must be reported, not silently left."""
        sock_path = tmp_path / "voice-daemon.sock"
        daemon = FakeDaemon(sock_path, honor_shutdown=False)
        try:
            with patch("vibe_rtts.daemon.SOCKET_PATH", sock_path):
                mgr = DaemonManager()
                errors = []
                mgr.engine_error.connect(errors.append)
                mgr.start()
                with patch.object(mgr, "_find_daemon_pids", return_value=[]):
                    mgr.stop()
                assert errors and "GPU memory" in errors[0]
        finally:
            daemon.close()

    def test_cpu_daemon_is_not_adopted(self, tmp_path):
        sock_path = tmp_path / "voice-daemon.sock"
        daemon = FakeDaemon(sock_path, device="cpu")
        try:
            with patch("vibe_rtts.daemon.SOCKET_PATH", sock_path):
                mgr = DaemonManager()
                ready = MagicMock()
                errors = []
                mgr.engine_ready.connect(ready)
                mgr.engine_error.connect(errors.append)

                mgr.start()
                ready.assert_not_called()
                assert mgr._adopted is False
                assert errors and "CPU" in errors[0]
        finally:
            daemon.close()

    def test_legacy_daemon_without_device_command_is_adopted(self, tmp_path):
        """Older daemons answer garbage to 'device'; adopt them anyway."""
        sock_path = tmp_path / "voice-daemon.sock"
        daemon = FakeDaemon(sock_path, device="unsupported")
        try:
            with patch("vibe_rtts.daemon.SOCKET_PATH", sock_path):
                mgr = DaemonManager()
                ready = MagicMock()
                mgr.engine_ready.connect(ready)
                mgr.start()
                ready.assert_called_once()
                assert mgr._adopted is True
                assert mgr.device is None
        finally:
            daemon.close()


class TestCrashIsVisible:
    """A daemon that dies on its own (e.g. no VRAM) must not fail silently."""

    def test_nonzero_exit_reports_stderr(self):
        mgr = DaemonManager()
        errors = []
        stopped = MagicMock()
        mgr.engine_error.connect(errors.append)
        mgr.engine_stopped.connect(stopped)

        mgr._stderr_tail = ["FATAL: could not load large-v3 on cuda: out of memory"]
        mgr._on_process_finished(1, None)

        assert errors and "out of memory" in errors[0]
        stopped.assert_not_called()

    def test_deliberate_stop_does_not_report_an_error(self):
        mgr = DaemonManager()
        errors = []
        mgr.engine_error.connect(errors.append)

        mgr._stopping = True
        mgr._on_process_finished(9, None)
        assert errors == []
