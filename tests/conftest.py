import sys
import tempfile
from unittest.mock import MagicMock

import pytest


def pytest_configure(config):
    # macOS puts pytest's tmp_path under /var/folders/<long hash>/..., which blows
    # the 104-byte limit of an AF_UNIX path: every FakeDaemon would fail to bind.
    if sys.platform == "darwin" and not config.option.basetemp:
        config.option.basetemp = tempfile.mkdtemp(prefix="vrtts-", dir="/tmp")


@pytest.fixture(autouse=True)
def _isolate_tray_side_effects(monkeypatch, tmp_path):
    """Keep tests away from the real desktop and the real running app.

    A finished transcription copies to the clipboard and, on macOS, may post ⌘V
    into whatever app has the focus — the test runner's own window included.
    Settings would land in the user's real preferences. DaemonManager.stop()
    and _on_process_finished() unlink the daemon socket: on the real path that
    silently broke the running app, whose recordings then went nowhere. Tests
    that exercise these paths patch them on purpose; everyone else gets doubles.
    """
    import vibe_rtts.daemon as daemon
    import vibe_rtts.transcriber as transcriber
    import vibe_rtts.tray as tray
    from PySide6.QtCore import QSettings

    fake_socket = tmp_path / "voice-daemon.sock"
    monkeypatch.setattr(daemon, "SOCKET_PATH", fake_socket)
    monkeypatch.setattr(transcriber, "SOCKET_PATH", fake_socket)

    monkeypatch.setattr(tray, "copy_to_clipboard", MagicMock(return_value=True))
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(tray, "QSettings", lambda *_: QSettings(ini, QSettings.Format.IniFormat))
    if sys.platform == "darwin":
        import vibe_rtts.paste_macos as paste_macos
        monkeypatch.setattr(paste_macos, "paste_command_v", MagicMock())
        monkeypatch.setattr(paste_macos, "focused_text_input", MagicMock(return_value=False))
        monkeypatch.setattr(paste_macos, "wake_focused_app", MagicMock())
