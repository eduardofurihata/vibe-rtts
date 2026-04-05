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

# Shortcut
SHORTCUT_COMPONENT = "vibe-rtts"
SHORTCUT_ACTION = "voice-toggle"
# Meta+Shift+V: Qt::META(0x10000000) | Qt::SHIFT(0x02000000) | Qt::Key_V(0x56)
SHORTCUT_KEY_CODE = 0x12000056


def get_nvidia_ld_path() -> str:
    """Build LD_LIBRARY_PATH from nvidia libs in the venv."""
    pattern = str(VENV_PATH / "lib" / "python*" / "site-packages" / "nvidia" / "*" / "lib")
    dirs = glob.glob(pattern)
    return ":".join(dirs)
