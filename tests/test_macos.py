"""macOS port: config branches, Carbon shortcuts, clipboard and ⌃. paste."""
import os
import subprocess
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

from PySide6.QtWidgets import QApplication

from vibe_rtts import config
from vibe_rtts.proc import copy_to_clipboard
from vibe_rtts.tray import AppState, TrayManager
from tests.fakes import pump_until

app = QApplication.instance() or QApplication([])


class TestConfig:
    def test_runs_on_metal_not_cuda(self):
        assert config.DAEMON_DEVICE == "mps"
        assert "mlx" in config.DAEMON_MODEL
        assert config.VENV_PATH == config.PROJECT_DIR / ".venv"

    def test_captures_with_avfoundation(self):
        assert config.AUDIO_INPUT[:2] == ["-f", "avfoundation"]

    def test_shortcuts_are_control_comma_and_period(self):
        assert config.SHORTCUT_TOGGLE_DISPLAY == "⌃,"
        assert config.SHORTCUT_PASTE_DISPLAY == "⌃."
        assert "⌃." in config.PASTE_HINT


class TestMacShortcutHandler:
    @pytest.fixture
    def handler(self):
        from vibe_rtts.shortcut_macos import MacShortcutHandler
        h = MacShortcutHandler()
        yield h
        h.cleanup()

    def test_both_hotkeys_register(self, handler):
        assert handler._handler_ref is not None
        assert len(handler._hotkey_refs) == 2

    def test_toggle_id_emits_toggle_only(self, handler):
        toggle, paste = MagicMock(), MagicMock()
        handler.shortcut_activated.connect(toggle)
        handler.paste_activated.connect(paste)
        handler._dispatch(1)
        toggle.assert_called_once()
        paste.assert_not_called()

    def test_paste_id_emits_paste_only(self, handler):
        toggle, paste = MagicMock(), MagicMock()
        handler.shortcut_activated.connect(toggle)
        handler.paste_activated.connect(paste)
        handler._dispatch(2)
        paste.assert_called_once()
        toggle.assert_not_called()

    def test_repeat_within_debounce_is_ignored(self, handler):
        toggle = MagicMock()
        handler.shortcut_activated.connect(toggle)
        handler._dispatch(1)
        handler._dispatch(1)
        toggle.assert_called_once()

    def test_cleanup_is_idempotent(self, handler):
        handler.cleanup()
        handler.cleanup()
        assert handler._hotkey_refs == []
        assert handler._handler_ref is None


def _pbpaste() -> str:
    """Read the pasteboard the way another app would.

    Qt promises the data and hands it over through its event loop when someone
    asks, so a blocking pbpaste from this very process would deadlock: run it in
    a thread and keep the loop turning, as the real app's loop does.
    """
    out = {}
    reader = threading.Thread(target=lambda: out.update(text=subprocess.run(
        ["pbpaste"], capture_output=True, text=True, timeout=10).stdout))
    reader.start()
    assert pump_until(lambda: not reader.is_alive(), 10_000)
    return out["text"]


class TestClipboard:
    def test_text_reaches_the_system_pasteboard_with_accents(self):
        before = _pbpaste()
        text = "transcrição ação ✓"
        try:
            assert copy_to_clipboard(text, "TEST") is True
            assert _pbpaste() == text
        finally:
            copy_to_clipboard(before, "TEST")


class TestPaste:
    def test_without_accessibility_warns_and_does_not_paste(self):
        tray = TrayManager()
        tray.showMessage = MagicMock()
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=False) as trusted, \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            tray._on_paste()
            tray._on_paste()
            pump_until(lambda: False, 200)
        paste.assert_not_called()
        assert tray.showMessage.call_count == 2
        assert "Accessibility" in tray.showMessage.call_args[0][1]
        # macOS's own dialog only once, not on every press
        assert [c.kwargs.get("prompt") for c in trusted.call_args_list].count(True) == 1

    def test_with_accessibility_posts_command_v(self):
        tray = TrayManager()
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=True), \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            tray._on_paste()
            assert pump_until(lambda: paste.called, 1000)


class TestAutoPaste:
    """Stopping a recording pastes by itself only when the cursor is in a text field."""

    def _finish(self, tray):
        tray.showMessage = MagicMock()
        tray._on_transcription_done("olá mundo", "pt")
        pump_until(lambda: tray.showMessage.called, 2000)
        return tray.showMessage.call_args[0][1]

    def test_on_by_default(self):
        assert TrayManager()._auto_paste is True

    def test_text_field_focused_pastes(self):
        tray = TrayManager()
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=True), \
                patch("vibe_rtts.paste_macos.focused_text_input", return_value=True), \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            message = self._finish(tray)
        paste.assert_called_once()
        assert "Pasted" in message

    def test_no_text_field_only_copies(self):
        tray = TrayManager()
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=True), \
                patch("vibe_rtts.paste_macos.focused_text_input", return_value=False), \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            message = self._finish(tray)
        paste.assert_not_called()
        assert "Copied" in message and "⌃." in message

    def test_switched_off_never_pastes(self):
        tray = TrayManager()
        tray._auto_paste_action.setChecked(False)
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=True), \
                patch("vibe_rtts.paste_macos.focused_text_input", return_value=True), \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            message = self._finish(tray)
        paste.assert_not_called()
        assert "Copied" in message

    def test_switch_is_remembered(self):
        TrayManager()._auto_paste_action.setChecked(False)
        assert TrayManager()._auto_paste is False

    def test_without_accessibility_does_not_paste_nor_prompt(self):
        tray = TrayManager()
        with patch("vibe_rtts.paste_macos.is_trusted", return_value=False) as trusted, \
                patch("vibe_rtts.paste_macos.paste_command_v") as paste:
            message = self._finish(tray)
        paste.assert_not_called()
        assert "Copied" in message
        assert all(not c.kwargs.get("prompt") for c in trusted.call_args_list)

    def test_recording_start_wakes_the_focused_app(self):
        tray = TrayManager()
        tray.recorder = MagicMock()
        tray._update_state(AppState.READY)
        with patch("vibe_rtts.paste_macos.wake_focused_app") as wake:
            tray._on_toggle()
        wake.assert_called_once()


class TestFocusDetectionSmoke:
    def test_real_query_returns_a_bool(self):
        import importlib
        import vibe_rtts.paste_macos as pm
        real = importlib.reload(pm)  # undo the autouse double: hit the real AX API
        try:
            assert isinstance(real.focused_text_input(), bool)
        finally:
            importlib.reload(pm)
