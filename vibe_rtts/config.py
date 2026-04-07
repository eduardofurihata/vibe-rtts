from pathlib import Path
import glob

APP_NAME = "vibe-rtts"
APP_DISPLAY_NAME = "Vibe RTTS"
DBUS_SERVICE = "com.github.furihata.vibe_rtts"

# Paths
PROJECT_DIR = Path(__file__).resolve().parent.parent
VENV_PATH = Path.home() / "GitHub" / "vibe-whisper-transcriber" / ".venv"
PYTHON_PATH = VENV_PATH / "bin" / "python"
DAEMON_SCRIPT = PROJECT_DIR / "daemon" / "voice_daemon.py"
SOCKET_PATH = Path("/tmp/voice-daemon.sock")
RAW_FILE = Path("/tmp/vibe-rtts-recording.raw")
WAV_FILE = Path("/tmp/vibe-rtts-recording.wav")
ICONS_DIR = PROJECT_DIR / "vibe_rtts" / "icons"

# Data
DATA_DIR = Path.home() / ".local" / "share" / APP_NAME
DB_PATH = DATA_DIR / "history.db"

# Daemon
DAEMON_MODEL = "large-v3"
DAEMON_DEVICE = "cuda"
DAEMON_COMPUTE_TYPE = "int8"

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


def get_nvidia_ld_path() -> str:
    """Build LD_LIBRARY_PATH from nvidia libs in the venv."""
    pattern = str(VENV_PATH / "lib" / "python*" / "site-packages" / "nvidia" / "*" / "lib")
    dirs = glob.glob(pattern)
    return ":".join(dirs)
