from pathlib import Path
import glob
import os
import sys

IS_MACOS = sys.platform == "darwin"

APP_NAME = "vibe-rtts"
APP_DISPLAY_NAME = "Vibe RTTS"
DBUS_SERVICE = "com.github.furihata.vibe_rtts"

# Paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
# Linux reuses the vibe-whisper-transcriber venv (CUDA torch); macOS has its own
# .venv in the project, created by `make setup-mac`.
if IS_MACOS:
    VENV_PATH = PROJECT_DIR / ".venv"
else:
    VENV_PATH = Path.home() / "GitHub" / "vibe-whisper-transcriber" / ".venv"
PYTHON_PATH = VENV_PATH / "bin" / "python"
DAEMON_SCRIPT = PROJECT_DIR / "daemon" / "voice_daemon.py"
SOCKET_PATH = Path("/tmp/voice-daemon.sock")
RAW_FILE = Path("/tmp/vibe-rtts-recording.raw")
WAV_FILE = Path("/tmp/vibe-rtts-recording.wav")
ICONS_DIR = PROJECT_DIR / "vibe_rtts" / "icons"

# Data
if IS_MACOS:
    DATA_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    DATA_DIR = Path.home() / ".local" / "share" / APP_NAME
DB_PATH = DATA_DIR / "history.db"

# Daemon
# There is no CUDA on a Mac, and faster-whisper cannot use the Apple GPU: there
# the daemon runs mlx-whisper on Metal ("mps"), with the turbo model.
if IS_MACOS:
    DAEMON_MODEL = "mlx-community/whisper-large-v3-turbo"
    DAEMON_DEVICE = "mps"
else:
    DAEMON_MODEL = "large-v3"
    DAEMON_DEVICE = "cuda"
DAEMON_COMPUTE_TYPE = "int8"

# Audio capture (ffmpeg input)
if IS_MACOS:
    AUDIO_INPUT = ["-f", "avfoundation", "-i", ":default"]
else:
    AUDIO_INPUT = ["-f", "pulse", "-i", "default"]

# Load the model as soon as the app opens, so the tray starts in READY instead of
# waiting for a click. Set VIBE_RTTS_AUTOSTART_ENGINE=0 to open without preloading
# (useful when another job needs the GPU memory).
AUTO_START_ENGINE = os.environ.get(
    "VIBE_RTTS_AUTOSTART_ENGINE", "1"
).strip().lower() not in ("0", "false", "no", "off")

# Shortcuts
SHORTCUT_COMPONENT = "vibe-rtts"

# Toggle recording: Ctrl+Alt+Space  OR  Numpad -
SHORTCUT_TOGGLE_ACTION = "voice-toggle"
SHORTCUT_TOGGLE_KEYS = [
    0x0C000020,  # Ctrl(0x04000000) | Alt(0x08000000) | Space(0x20)
    0x2000002D,  # Keypad(0x20000000) | Minus(0x2d)
]
SHORTCUT_TOGGLE_DISPLAY = "Ctrl+Alt+Space / Numpad -"

# Paste last transcription: Numpad +
SHORTCUT_PASTE_ACTION = "paste-last"
SHORTCUT_PASTE_KEYS = [
    0x2000002B,  # Keypad(0x20000000) | Plus(0x2b)
]
SHORTCUT_PASTE_DISPLAY = "Numpad +"

# Stop recording and copy, without pasting: macOS only.
SHORTCUT_STOP_COPY_DISPLAY = None

# macOS has no numpad on the MacBook and no kglobalaccel: Control+comma toggles
# (and pastes on stop), Control+period stops and only copies, Control+slash
# pastes. All three are free in the system and the common apps; in the terminal
# ⌃/ is readline's undo (^_), which the hotkey swallows while the app runs.
if IS_MACOS:
    SHORTCUT_TOGGLE_DISPLAY = "⌃,"
    SHORTCUT_STOP_COPY_DISPLAY = "⌃."
    SHORTCUT_PASTE_DISPLAY = "⌃/"

PASTE_HINT = "⌃/ or ⌘V" if IS_MACOS else "Ctrl+Shift+V"

# macOS: paste the transcription by itself when the cursor is in a text field
# (it stays on the clipboard either way). Toggle in the tray menu; persisted.
AUTO_PASTE_DEFAULT = True


def get_nvidia_ld_path() -> str:
    """Build LD_LIBRARY_PATH from nvidia libs in the venv."""
    pattern = str(VENV_PATH / "lib" / "python*" / "site-packages" / "nvidia" / "*" / "lib")
    dirs = glob.glob(pattern)
    return ":".join(dirs)
