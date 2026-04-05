import os

from PySide6.QtCore import QObject, Signal, QProcess

from vibe_rtts.config import RAW_FILE, WAV_FILE


class RecordingEngine(QObject):
    recording_started = Signal()
    recording_stopped = Signal(str)  # wav_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None

    def start_recording(self):
        # Clean previous files
        for f in (RAW_FILE, WAV_FILE):
            if f.exists():
                f.unlink()

        self._process = QProcess(self)
        self._process.setProgram("ffmpeg")
        self._process.setArguments([
            "-y",
            "-f", "pulse", "-i", "default",
            "-ac", "1", "-ar", "16000",
            "-f", "s16le",
            str(RAW_FILE),
        ])
        self._process.setStandardInputFile(os.devnull)
        self._process.setStandardOutputFile(os.devnull)
        self._process.setStandardErrorFile(os.devnull)
        self._process.start()
        self.recording_started.emit()

    def stop_recording(self):
        if not self._process or self._process.state() != QProcess.ProcessState.Running:
            return

        self._process.terminate()
        self._process.waitForFinished(3000)
        self._process = None

        # Convert raw PCM to WAV
        wav_path = self._convert_raw_to_wav()
        if wav_path:
            self.recording_stopped.emit(wav_path)

    def _convert_raw_to_wav(self) -> str | None:
        if not RAW_FILE.exists() or RAW_FILE.stat().st_size < 1000:
            return None

        conv = QProcess()
        conv.setProgram("ffmpeg")
        conv.setArguments([
            "-y",
            "-f", "s16le", "-ar", "16000", "-ac", "1",
            "-i", str(RAW_FILE),
            str(WAV_FILE),
        ])
        conv.setStandardInputFile(os.devnull)
        conv.start()
        conv.waitForFinished(5000)

        # Cleanup raw file
        RAW_FILE.unlink(missing_ok=True)

        if WAV_FILE.exists():
            return str(WAV_FILE)
        return None
