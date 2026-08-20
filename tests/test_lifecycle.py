"""Lifecycle regressions: the app must not abort, leak or get stuck.

Covers the automatable part of docs/05-test-cases/crash-and-resource-leaks.md
(TC-1, TC-2, TC-6, TC-7) plus the single-emission rule behind TC-2/UC-13.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from PySide6.QtCore import QProcess, QThread
from PySide6.QtWidgets import QApplication

from vibe_rtts.daemon import DaemonManager
from vibe_rtts.proc import StderrTail, run_detached
from vibe_rtts.recorder import RecordingEngine
from vibe_rtts.transcriber import TranscribeWorker
from vibe_rtts.tray import TrayManager, AppState
from tests.fakes import FakeDaemon, pump_until

app = QApplication.instance() or QApplication([])


def _make_tray():
    tray = TrayManager()
    tray.daemon_manager = MagicMock()
    tray.recorder = MagicMock()
    return tray


class TestWorkerLifetime:
    """TC-1: dropping a running QThread aborted the process (SIGABRT)."""

    def test_domain_signals_do_not_shadow_qthread_finished(self):
        assert TranscribeWorker.finished is QThread.finished
        assert hasattr(TranscribeWorker, "transcribed")
        assert hasattr(TranscribeWorker, "failed")

    def test_worker_reference_survives_the_result_handler(self):
        """The reference may only be dropped by the native finished signal."""
        tray = _make_tray()
        sentinel = MagicMock()
        tray._transcribe_worker = sentinel

        tray._on_transcription_done("some text", "pt")
        assert tray._transcribe_worker is sentinel, "released while the thread may still run"

        tray._on_worker_finished()
        assert tray._transcribe_worker is None

    def test_worker_reference_survives_the_error_handler(self):
        tray = _make_tray()
        sentinel = MagicMock()
        tray._transcribe_worker = sentinel

        tray._on_transcription_error("boom")
        assert tray._transcribe_worker is sentinel
        assert tray._state == AppState.READY

    def test_repeated_real_transcriptions_do_not_abort(self, tmp_path):
        """The regression itself: run real threads to completion, repeatedly.

        If the worker were destroyed while running, Qt would qFatal and take the
        whole test process down — so reaching the asserts is the proof.
        """
        sock_path = tmp_path / "voice-daemon.sock"
        daemon = FakeDaemon(sock_path)
        wav = tmp_path / "audio.wav"
        wav.write_bytes(b"RIFF....WAVEfmt ")
        try:
            with patch("vibe_rtts.transcriber.SOCKET_PATH", sock_path):
                for _ in range(20):
                    tray = _make_tray()
                    tray._update_state(AppState.RECORDING)
                    tray._on_recording_stopped(str(wav))
                    assert pump_until(lambda: tray._transcribe_worker is None), \
                        "worker never reported finished"
                    assert tray._state == AppState.READY
        finally:
            daemon.close()


class TestImmediateFeedback:
    """UC-10 / US-5: the icon must leave RECORDING when the user says stop."""

    def test_toggle_leaves_recording_before_the_wav_exists(self):
        tray = _make_tray()
        tray._update_state(AppState.RECORDING)

        tray._on_toggle()  # the recorder is a mock: no signal will come back

        assert tray._state == AppState.TRANSCRIBING, \
            "user waits for the conversion before seeing any feedback"
        tray.recorder.stop_recording.assert_called_once()

    def test_recording_stopped_does_not_re_announce_the_state(self):
        tray = _make_tray()
        tray._update_state(AppState.RECORDING)
        tray._on_toggle()

        # The worker is stubbed on purpose: a real QThread left running past the
        # end of this test would be destroyed while active — the very abort this
        # feature fixes, and a test must not reintroduce it.
        with patch("vibe_rtts.transcriber.TranscribeWorker"), \
             patch.object(tray, "_update_state") as update:
            tray._on_recording_stopped("/tmp/whatever.wav")
            update.assert_not_called()


class TestRecordingFailureUnsticksTheUI:
    """TC-6 / TC-7: a failed capture must never leave the tray on RECORDING."""

    def test_failure_returns_to_ready_while_recording(self):
        tray = _make_tray()
        tray._update_state(AppState.RECORDING)

        tray._on_recording_failed("No audio captured: device busy")
        assert tray._state == AppState.READY

    def test_failure_does_not_resurrect_a_dead_engine(self):
        """If the engine died mid-recording, engine_stopped already took us to
        INACTIVE — a late capture failure must not paint us READY again."""
        tray = _make_tray()
        tray._update_state(AppState.RECORDING)
        tray._on_engine_stopped()
        assert tray._state == AppState.INACTIVE

        tray._on_recording_failed("Recording stopped unexpectedly (exit 1)")
        assert tray._state == AppState.INACTIVE

    def test_stopping_a_dead_capture_reports_instead_of_going_silent(self):
        """Used to return early, leaving RECORDING with nothing left to stop."""
        recorder = RecordingEngine()
        reasons = []
        recorder.recording_failed.connect(reasons.append)

        recorder.stop_recording()  # never started
        assert reasons and "not active" in reasons[0]

    def test_missing_binary_is_reported_with_a_reason(self, tmp_path, monkeypatch):
        recorder = RecordingEngine()
        reasons = []
        recorder.recording_failed.connect(reasons.append)

        monkeypatch.setattr("vibe_rtts.recorder.RAW_FILE", tmp_path / "raw")
        monkeypatch.setattr("vibe_rtts.recorder.WAV_FILE", tmp_path / "out.wav")
        monkeypatch.setattr("vibe_rtts.recorder._FFMPEG", "ffmpeg-does-not-exist")

        recorder.start_recording()
        assert pump_until(lambda: bool(reasons)), "no failure reported for a missing binary"
        assert "ffmpeg" in reasons[0]


class TestAbortOnShutdown:
    """UC-3 / UC-5: quitting must not leave ffmpeg recording behind."""

    def test_abort_kills_a_running_capture_without_reporting(self):
        recorder = RecordingEngine()
        reasons = []
        stopped = []
        recorder.recording_failed.connect(reasons.append)
        recorder.recording_stopped.connect(stopped.append)

        # A long-lived stand-in for the ffmpeg capture
        capture = QProcess(recorder)
        capture.setProgram("sleep")
        capture.setArguments(["300"])
        capture.start()
        assert pump_until(lambda: capture.state() == QProcess.ProcessState.Running)
        recorder._process = capture

        recorder.abort()
        assert capture.state() == QProcess.ProcessState.NotRunning, "capture survived abort"
        assert recorder._process is None
        assert reasons == [] and stopped == [], "abort must be silent"


    def test_abort_stops_queued_signals_from_restarting_work(self, tmp_path, monkeypatch):
        """A finished() already in flight used to start the conversion mid-shutdown."""
        recorder = RecordingEngine()
        stopped, failed = [], []
        recorder.recording_stopped.connect(stopped.append)
        recorder.recording_failed.connect(failed.append)

        raw = tmp_path / "raw"
        raw.write_bytes(b"\x00" * 64000)  # plenty of audio, so conversion would run
        monkeypatch.setattr("vibe_rtts.recorder.RAW_FILE", raw)
        monkeypatch.setattr("vibe_rtts.recorder.WAV_FILE", tmp_path / "out.wav")

        recorder.abort()
        recorder._on_capture_finished(0, None)  # the queued signal lands now

        assert recorder._converter is None, "conversion started while shutting down"
        assert stopped == [] and failed == []


class TestStderrTail:
    """TC-7: the reason a process died has to reach the user."""

    def test_collects_stderr_lines(self):
        process = QProcess()
        tail = StderrTail(process, "TEST")
        process.setProgram("sh")
        process.setArguments(["-c", "echo 'device or resource busy' >&2; exit 1"])
        process.start()
        assert pump_until(lambda: tail.text() != "")
        assert "resource busy" in tail.text()

    def test_keeps_only_the_last_lines(self):
        process = QProcess()
        tail = StderrTail(process, "TEST", keep=2)
        process.setProgram("sh")
        process.setArguments(["-c", "for i in 1 2 3 4 5; do echo line$i >&2; done"])
        process.start()
        assert pump_until(
            lambda: process.state() == QProcess.ProcessState.NotRunning and tail.text()
        )
        assert "line1" not in tail.text()
        assert "line5" in tail.text()


class TestDetachedHelpers:
    """US-2: helper processes must not pile up as zombies."""

    def test_run_detached_leaves_no_child_to_reap(self):
        import os
        assert run_detached("true", [], "TEST") is True
        # A detached process is not our child, so waiting must find nothing.
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            pid = 0
        assert pid == 0, f"process {pid} was left for us to reap"

    def test_run_detached_reports_a_missing_program(self):
        assert run_detached("definitely-not-a-real-binary", [], "TEST") is False


class TestSingleStopEvent:
    """UC-13 / TC-2: one failure is one event, not two."""

    class _AlreadyReapedProcess:
        """A process whose terminate() lets the finished handler run first.

        That is what waitForFinished does in production (it pumps events), and it
        used to make stop() emit engine_stopped a second time.
        """

        def __init__(self, manager):
            self._manager = manager

        def state(self):
            return QProcess.ProcessState.Running

        def terminate(self):
            self._manager._on_process_finished(0, None)

        def waitForFinished(self, _ms):
            return True

    def test_stop_emits_engine_stopped_once(self):
        manager = DaemonManager()
        events = []
        manager.engine_stopped.connect(lambda: events.append("stopped"))
        manager._process = self._AlreadyReapedProcess(manager)

        manager.stop()
        assert events == ["stopped"], f"expected exactly one event, got {events}"

    def test_stop_still_reports_when_no_process_was_running(self):
        manager = DaemonManager()
        events = []
        manager.engine_stopped.connect(lambda: events.append("stopped"))

        manager.stop()
        assert events == ["stopped"]
