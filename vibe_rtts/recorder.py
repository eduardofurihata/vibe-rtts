import os

from PySide6.QtCore import QObject, Signal, QProcess, QTimer

from vibe_rtts.config import AUDIO_INPUT, RAW_FILE, WAV_FILE
from vibe_rtts.proc import StderrTail

_FFMPEG = "ffmpeg"
# Without these, ffmpeg writes a 4KB configuration banner plus a progress line
# twice a second — which would drown the log and, worse, would be what the "last
# lines of stderr" report as the cause of a failure.
_FFMPEG_QUIET = ["-hide_banner", "-loglevel", "error", "-nostats"]
# Below this, the capture produced no usable audio (500 samples of 16kHz mono s16le).
_MIN_RAW_BYTES = 1000
# How long ffmpeg gets to flush and exit after terminate() before we kill it.
_KILL_GRACE_MS = 3000


class RecordingEngine(QObject):
    """Captures audio with ffmpeg and hands back a wav — or an explained failure.

    Everything is driven by QProcess signals: blocking the GUI thread while
    ffmpeg finishes would freeze the tray for as long as it takes to stop.
    """

    recording_stopped = Signal(str)  # wav_path
    recording_failed = Signal(str)   # reason, shown to the user

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._stderr = None
        self._converter = None
        self._converter_stderr = None
        self._stopping = False
        self._shutting_down = False

        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(_KILL_GRACE_MS)
        self._kill_timer.timeout.connect(self._force_kill)

    def start_recording(self):
        self._shutting_down = False
        for f in (RAW_FILE, WAV_FILE):
            f.unlink(missing_ok=True)

        self._stopping = False
        self._process = QProcess(self)
        self._process.setProgram(_FFMPEG)
        self._process.setArguments([
            "-y", *_FFMPEG_QUIET,
            *AUDIO_INPUT,
            "-ac", "1", "-ar", "16000",
            "-f", "s16le",
            str(RAW_FILE),
        ])
        self._process.setStandardInputFile(os.devnull)
        self._process.setStandardOutputFile(os.devnull)
        self._stderr = StderrTail(self._process, "FFMPEG")
        self._process.finished.connect(self._on_capture_finished)
        self._process.errorOccurred.connect(self._on_capture_error)
        self._process.start()

    def abort(self):
        """Kill the capture without reporting anything — used when shutting down.

        stop_recording() is asynchronous, so the app could exit before ffmpeg did
        and leave it recording forever with nobody listening.
        """
        self._kill_timer.stop()
        self._stopping = True
        # Signals already queued must not restart work while we are going down:
        # a pending finished() would kick off the conversion, and its own
        # finished() would ask the tray to start a transcription thread.
        self._shutting_down = True
        for process in (self._process, self._converter):
            if process and process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(2000):
                    process.kill()
                    process.waitForFinished(1000)
        self._process = None
        self._converter = None

    def stop_recording(self):
        # Starting counts as active: ffmpeg may still be coming up, and letting it
        # go here would leave it recording with nobody to stop it.
        if not self._process or self._process.state() == QProcess.ProcessState.NotRunning:
            # The capture already died (bad device, missing binary). Say so instead
            # of returning silently, which used to leave the UI stuck on RECORDING.
            self._fail("Recording was not active — the capture had already stopped")
            return

        self._stopping = True
        self._process.terminate()  # ffmpeg needs the signal to close the raw file
        self._kill_timer.start()

    # --- capture lifecycle ---
    def _force_kill(self):
        # Not just Running: a process stuck in Starting also ignores terminate().
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            print("[RECORDER] ffmpeg ignored terminate; killing", flush=True)
            self._process.kill()

    def _on_capture_error(self, error):
        if self._shutting_down:
            return
        if self._stopping:
            return  # terminate()/kill() reports Crashed; that one is ours
        if error == QProcess.ProcessError.FailedToStart:
            # Qt emits no finished() for a process that never started, so nobody
            # else will clear this.
            self._process = None
        self._fail(self._reason(f"ffmpeg failed to start ({error})"))

    def _on_capture_finished(self, exit_code, exit_status):
        if self._shutting_down:
            return
        self._kill_timer.stop()
        stopped_by_us = self._stopping
        self._stopping = False
        self._process = None

        if not stopped_by_us:
            # ffmpeg died on its own — the audio device went away mid-recording
            # (a Bluetooth headset switching is enough to do it).
            self._fail(self._reason(f"Recording stopped unexpectedly (exit {exit_code})"))
            return

        self._convert_raw_to_wav()

    # --- conversion lifecycle ---
    def _convert_raw_to_wav(self):
        if self._shutting_down:
            return
        if not RAW_FILE.exists() or RAW_FILE.stat().st_size < _MIN_RAW_BYTES:
            RAW_FILE.unlink(missing_ok=True)
            self._fail(self._reason("No audio captured"))
            return

        self._converter = QProcess(self)
        self._converter.setProgram(_FFMPEG)
        self._converter.setArguments([
            "-y", *_FFMPEG_QUIET,
            "-f", "s16le", "-ar", "16000", "-ac", "1",
            "-i", str(RAW_FILE),
            str(WAV_FILE),
        ])
        self._converter.setStandardInputFile(os.devnull)
        self._converter.setStandardOutputFile(os.devnull)
        self._converter_stderr = StderrTail(self._converter, "FFMPEG-CONV")
        self._converter.finished.connect(self._on_convert_finished)
        self._converter.errorOccurred.connect(self._on_convert_error)
        self._converter.start()

    def _on_convert_error(self, error):
        self._converter = None
        RAW_FILE.unlink(missing_ok=True)
        self._fail(f"Could not convert the recording ({error})")

    def _on_convert_finished(self, exit_code, exit_status):
        if self._shutting_down:
            return
        stderr = self._converter_stderr.text() if self._converter_stderr else ""
        self._converter = None
        self._converter_stderr = None
        RAW_FILE.unlink(missing_ok=True)

        if WAV_FILE.exists():
            self.recording_stopped.emit(str(WAV_FILE))
        else:
            self._fail(f"Could not convert the recording: {stderr or f'exit {exit_code}'}")

    # --- helpers ---
    def _reason(self, headline: str) -> str:
        """Headline plus whatever ffmpeg said, so the user can act on it."""
        detail = self._stderr.text() if self._stderr else ""
        return f"{headline}: {detail}" if detail else headline

    def _fail(self, reason: str):
        print(f"[RECORDER] {reason}", flush=True)
        self.recording_failed.emit(reason)
