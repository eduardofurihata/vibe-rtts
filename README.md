# Vibe RTTS

System tray voice-to-text app for Linux. Records audio, transcribes with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and copies
the result to your clipboard.

## How It Works

- A **system tray icon** shows the current state (inactive/ready/recording/transcribing)
- Press **Meta+Shift+V** or **double-click the tray icon** to toggle recording
- Audio is recorded via PulseAudio/PipeWire, transcribed by a local Whisper
  model running on CUDA, and copied to the Wayland clipboard
- Transcription history is stored locally in SQLite

## Requirements

- Linux with Wayland (tested on KDE Plasma)
- PulseAudio or PipeWire (for audio capture via ffmpeg)
- NVIDIA GPU with CUDA support
- [vibe-whisper-transcriber](https://github.com/furihata/vibe-whisper-transcriber)
  venv (provides PySide6, faster-whisper, torch)
- `wl-copy` (from wl-clipboard, for Wayland clipboard)
- `ffmpeg` (for audio recording/conversion)

## Quick Start

```bash
# Run and register in app launcher (start menu)
make dev

# Run directly
make run

# Install to ~/bin
make install

# Remove shortcut and ~/bin link
make uninstall
```

## Project Structure

```
vibe_rtts/
  app.py             # Application entry point, wires components
  tray.py            # System tray icon and state machine
  daemon.py          # Manages the whisper transcription daemon
  recorder.py        # Audio recording via ffmpeg/PulseAudio
  transcriber.py     # Sends audio to daemon, receives text
  shortcut.py        # Global hotkey via KDE kglobalaccel (DBus)
  history.py         # SQLite storage for transcriptions
  history_window.py  # Qt history browser window
  config.py          # Paths, constants, configuration
  icons/             # Tray icon PNGs for each state
daemon/
  voice_daemon.py    # Whisper model server (Unix socket)
scripts/
  vibe-rtts.sh       # Launcher (sets CUDA LD_LIBRARY_PATH)
```

## States

| State | Icon | Description |
|-------|------|-------------|
| INACTIVE | Grey mic | Engine stopped, GPU free |
| LOADING | Grey mic | Starting daemon, loading model |
| READY | Green mic | Ready to record |
| RECORDING | Red mic (pulsing) | Recording audio |
| TRANSCRIBING | Green mic | Processing transcription |
