# Vibe RTTS

System tray voice-to-text app for Linux and macOS. Records audio, transcribes with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and copies
the result to your clipboard.

## How It Works

- A **system tray icon** shows the current state (inactive/ready/recording/transcribing)
- On launch the model is **preloaded**, so the app opens straight in READY — no
  first click to warm it up. "Stop Engine" in the tray menu frees the GPU memory
- Press **Ctrl+Alt+Space**, **Numpad -**, or **double-click the tray icon** to toggle recording
- Press **Numpad +** to paste the last transcription into the focused window
- Audio is recorded via PulseAudio/PipeWire, transcribed by a local Whisper
  model running on CUDA, and copied to the Wayland clipboard
- Transcription history is stored locally in SQLite
- The GPU is mandatory: `large-v3` on CPU is too slow to be usable, so the daemon
  refuses to start rather than silently falling back (pass `--allow-cpu-fallback`
  to the daemon if you really want it)
- If the capture fails — a Bluetooth headset switching the default device is
  enough — the tray says why and returns to idle instead of staying stuck on
  "recording"
- The model daemon dies with the app, including when the app is killed or
  crashes, so it never sits on the GPU memory afterwards

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

# Open without preloading the model (leaves the VRAM free for another job)
VIBE_RTTS_AUTOSTART_ENGINE=0 vibe-rtts
```

## macOS

The same app runs on Apple Silicon Macs, with the platform pieces swapped:

| | Linux | macOS |
|---|---|---|
| Toggle recording | Ctrl+Alt+Space / Numpad − | **⌃ ,** (Control + comma) |
| Paste last transcription | Numpad + | **⌃ .** (Control + period), or just ⌘V |
| Engine | faster-whisper on CUDA, `large-v3` | mlx-whisper on the Apple GPU, `whisper-large-v3-turbo` |
| Audio | PulseAudio/PipeWire | AVFoundation (default input) |
| Clipboard | `wl-copy` | NSPasteboard (Qt) |

**Auto-paste:** when you stop a recording with the cursor in a text field, the
text is pasted right there. It always lands on the clipboard too, so if the focus
was elsewhere, ⌃. or ⌘V paste it later. Switch it off with "Auto-paste into text
fields" in the tray menu (remembered across restarts).

⌃, and ⌃. are free in macOS, in the common apps and in the terminal; the
🎤/F5 key keeps opening the system dictation. The shortcuts are registered with
Carbon's `RegisterEventHotKey`, which needs no special permission.

```bash
make setup-mac      # brew ffmpeg + ./.venv with PySide6 and mlx-whisper
make install-mac    # ~/Applications/Vibe RTTS.app, opened now and at every login
make uninstall-mac  # removes the app and the login agent
make run            # or run it from the terminal instead
```

The app lives in the menu bar only (no Dock icon). Opening "Vibe RTTS" from
Spotlight or Finder starts it — or, if it is already running, shows a notification
saying so. It points at this repo, so a `git pull` updates it without reinstalling.
Logs: `~/Library/Logs/vibe-rtts.log`. The first start downloads the model (~1.6 GB).

Under the hood a launchd agent runs the app through the bundle's compiled
launcher (`scripts/macos/launcher.c`), and a click on the bundle only starts that
agent. Each piece is there for a reason found the hard way:

- started by a click (LaunchServices), macOS 27 hides the menu bar icon of a
  process owned by a new, unsigned bundle — launchd-started, it shows;
- the launcher stays alive as the app's parent, so the Microphone permission
  belongs to "Vibe RTTS" and macOS can ask for it;
- the agent is `ProcessType=Interactive`: as default background work macOS
  throttled it and ffmpeg kept under a third of the audio, which Whisper turned
  into "Thank you." / "Hola.".

Recordings with no speech (silence, room noise) are reported as "No speech
detected" instead of being transcribed: mlx-whisper has no VAD and invents text
for silence, which auto-paste would then type into your document.

macOS asks for two permissions, for "Vibe RTTS" (or your terminal with `make run`):

- **Microphone** — asked on the first recording.
- **Accessibility** — only for ⌃. (posting ⌘V into the focused app). Without it,
  the tray tells you where to enable it, and ⌘V keeps working.

## Project Structure

```
vibe_rtts/
  app.py             # Application entry point, wires components
  tray.py            # System tray icon and state machine
  daemon.py          # Manages the whisper transcription daemon
  recorder.py        # Audio recording via ffmpeg/PulseAudio
  transcriber.py     # Sends audio to daemon, receives text
  shortcut.py        # Global hotkey via KDE kglobalaccel (DBus)
  shortcut_macos.py  # Global hotkey via Carbon RegisterEventHotKey (macOS)
  paste_macos.py     # ⌘V via CoreGraphics + Accessibility check (macOS)
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
| TRANSCRIBING | Amber mic | Processing transcription; back to green when the text is on the clipboard |
