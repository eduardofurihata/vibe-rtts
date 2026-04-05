"""Tests for double-click detection on the tray icon."""
import sys
import os

# Add project root to path so vibe_rtts can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtCore import QTimer

from vibe_rtts.tray import TrayManager, AppState

# Need a QApplication instance for Qt widgets
app = QApplication.instance() or QApplication([])


class TestTrayDoubleClick:
    """Double-clicking the tray icon should trigger _on_toggle."""

    def _make_tray(self):
        """Create a TrayManager with mocked components."""
        tray = TrayManager()
        tray.daemon_manager = MagicMock()
        tray.recorder = MagicMock()
        return tray

    def test_two_trigger_events_calls_toggle(self):
        """Two rapid Trigger activations (SNI double-click) should call _on_toggle."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            mock_toggle.assert_called_once()

    def test_single_trigger_does_not_call_toggle(self):
        """A single Trigger activation should NOT call _on_toggle."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            # Simulate timeout expiring
            tray._on_click_timeout()
            mock_toggle.assert_not_called()

    def test_native_double_click_calls_toggle(self):
        """A native DoubleClick event should also call _on_toggle."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
            tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
            mock_toggle.assert_called_once()

    def test_click_count_resets_after_timeout(self):
        """After timeout, click count resets so next double-click works."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            # First single click + timeout
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            tray._on_click_timeout()

            # Now double-click should work
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            mock_toggle.assert_called_once()

    def test_click_count_resets_after_double_click(self):
        """After a successful double-click, count resets for the next one."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            # First double-click
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)

            # Second double-click
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
            assert mock_toggle.call_count == 2

    def test_context_trigger_ignored(self):
        """Context menu activation should not count as a click."""
        tray = self._make_tray()
        with patch.object(tray, '_on_toggle') as mock_toggle:
            tray._on_activated(QSystemTrayIcon.ActivationReason.Context)
            tray._on_activated(QSystemTrayIcon.ActivationReason.Context)
            mock_toggle.assert_not_called()
