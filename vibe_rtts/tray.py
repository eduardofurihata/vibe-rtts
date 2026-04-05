from enum import Enum, auto

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer, Slot

from vibe_rtts.config import ICONS_DIR, APP_DISPLAY_NAME


class AppState(Enum):
    INACTIVE = auto()    # Daemon stopped, GPU free
    LOADING = auto()     # Daemon starting, model loading
    READY = auto()       # Daemon running, ready to record
    RECORDING = auto()   # Recording audio
    TRANSCRIBING = auto()  # Processing transcription


class TrayManager(QSystemTrayIcon):
    def __init__(self):
        super().__init__()
        self._state = AppState.INACTIVE

        # Load icons
        self._icons = {
            "inactive": QIcon(str(ICONS_DIR / "mic-inactive.png")),
            "active": QIcon(str(ICONS_DIR / "mic-active.png")),
            "recording": QIcon(str(ICONS_DIR / "mic-recording.png")),
            "recording_pulse": QIcon(str(ICONS_DIR / "mic-recording-pulse.png")),
        }

        # Pulse animation for recording state
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(500)
        self._pulse_timer.timeout.connect(self._pulse_icon)
        self._pulse_on = False

        # Build menu
        self._menu = QMenu()
        self._engine_action = QAction("Start Engine", self._menu)
        self._engine_action.triggered.connect(self._on_engine_toggle)
        self._menu.addAction(self._engine_action)

        self._menu.addSeparator()

        self._history_action = QAction("History", self._menu)
        self._history_action.triggered.connect(self._on_history)
        self._menu.addAction(self._history_action)

        self._menu.addSeparator()

        self._quit_action = QAction("Quit", self._menu)
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self._update_state(AppState.INACTIVE)

        # Double-click on tray icon triggers toggle
        self.activated.connect(self._on_activated)

        # Components (set by app after init)
        self.daemon_manager = None
        self.recorder = None
        self.transcriber_cls = None
        self.shortcut_handler = None
        self.history_store = None
        self.history_window = None
        self._transcribe_worker = None

    def init_components(self, daemon_manager, recorder, transcriber_cls,
                        shortcut_handler, history_store, history_window):
        """Wire up all components after creation."""
        self.daemon_manager = daemon_manager
        self.recorder = recorder
        self.transcriber_cls = transcriber_cls
        self.shortcut_handler = shortcut_handler
        self.history_store = history_store
        self.history_window = history_window

        # Connect signals
        self.daemon_manager.engine_ready.connect(self._on_engine_ready)
        self.daemon_manager.engine_stopped.connect(self._on_engine_stopped)
        self.daemon_manager.engine_error.connect(self._on_engine_error)
        self.recorder.recording_stopped.connect(self._on_recording_stopped)
        self.shortcut_handler.shortcut_activated.connect(self._on_toggle)

    def _update_state(self, new_state: AppState):
        print(f"[TRAY] State: {self._state.name} → {new_state.name}", flush=True)
        self._state = new_state

        if new_state == AppState.INACTIVE:
            self.setIcon(self._icons["inactive"])
            self.setToolTip(f"{APP_DISPLAY_NAME} — Inactive")
            self._engine_action.setText("Start Engine")
            self._engine_action.setEnabled(True)
            self._pulse_timer.stop()

        elif new_state == AppState.LOADING:
            self.setIcon(self._icons["inactive"])
            self.setToolTip(f"{APP_DISPLAY_NAME} — Loading model...")
            self._engine_action.setText("Loading...")
            self._engine_action.setEnabled(False)
            self._pulse_timer.stop()

        elif new_state == AppState.READY:
            self.setIcon(self._icons["active"])
            self.setToolTip(f"{APP_DISPLAY_NAME} — Ready")
            self._engine_action.setText("Stop Engine")
            self._engine_action.setEnabled(True)
            self._pulse_timer.stop()

        elif new_state == AppState.RECORDING:
            self.setIcon(self._icons["recording"])
            self.setToolTip(f"{APP_DISPLAY_NAME} — Recording...")
            self._engine_action.setEnabled(False)
            self._pulse_on = False
            self._pulse_timer.start()

        elif new_state == AppState.TRANSCRIBING:
            self.setIcon(self._icons["active"])
            self.setToolTip(f"{APP_DISPLAY_NAME} — Transcribing...")
            self._engine_action.setEnabled(False)
            self._pulse_timer.stop()

    @Slot()
    def _pulse_icon(self):
        self._pulse_on = not self._pulse_on
        icon_key = "recording_pulse" if self._pulse_on else "recording"
        self.setIcon(self._icons[icon_key])

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_toggle()

    # --- Toggle (shortcut or double-click) ---
    @Slot()
    def _on_toggle(self):
        print(f"[TRAY] Toggle pressed! Current state: {self._state.name}", flush=True)
        if self._state == AppState.INACTIVE:
            # Start daemon then record
            self._update_state(AppState.LOADING)
            self._pending_record_after_load = True
            self.daemon_manager.start()

        elif self._state == AppState.READY:
            # Start recording
            self._update_state(AppState.RECORDING)
            self.recorder.start_recording()

        elif self._state == AppState.RECORDING:
            # Stop recording → transcribe
            self.recorder.stop_recording()
            # _on_recording_stopped will handle the rest

        # Ignore if LOADING or TRANSCRIBING (debounce)

    # --- Engine events ---
    @Slot()
    def _on_engine_ready(self):
        if getattr(self, '_pending_record_after_load', False):
            self._pending_record_after_load = False
            self._update_state(AppState.RECORDING)
            self.recorder.start_recording()
        else:
            self._update_state(AppState.READY)

    @Slot()
    def _on_engine_stopped(self):
        self._update_state(AppState.INACTIVE)

    @Slot(str)
    def _on_engine_error(self, error_msg):
        self.showMessage("Vibe RTTS", f"Engine error: {error_msg}",
                         QSystemTrayIcon.MessageIcon.Critical, 5000)
        self._update_state(AppState.INACTIVE)

    # --- Recording events ---
    @Slot(str)
    def _on_recording_stopped(self, wav_path):
        self._update_state(AppState.TRANSCRIBING)
        from vibe_rtts.transcriber import TranscribeWorker
        self._transcribe_worker = TranscribeWorker(wav_path)
        self._transcribe_worker.finished.connect(self._on_transcription_done)
        self._transcribe_worker.error.connect(self._on_transcription_error)
        self._transcribe_worker.start()

    @Slot(str, str)
    def _on_transcription_done(self, text, language):
        import subprocess
        # Copy to clipboard
        subprocess.Popen(["wl-copy", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Save to history
        if self.history_store:
            self.history_store.save(text, language)
        # Notify
        self.showMessage("Vibe RTTS",
                         "Copied! Ctrl+Shift+V to paste",
                         QSystemTrayIcon.MessageIcon.Information, 3000)
        self._update_state(AppState.READY)
        self._transcribe_worker = None

    @Slot(str)
    def _on_transcription_error(self, error_msg):
        self.showMessage("Vibe RTTS", f"Transcription failed: {error_msg}",
                         QSystemTrayIcon.MessageIcon.Critical, 3000)
        self._update_state(AppState.READY)
        self._transcribe_worker = None

    # --- Menu actions ---
    @Slot()
    def _on_engine_toggle(self):
        if self._state == AppState.INACTIVE:
            self._pending_record_after_load = False
            self._update_state(AppState.LOADING)
            self.daemon_manager.start()
        elif self._state == AppState.READY:
            self.daemon_manager.stop()

    @Slot()
    def _on_history(self):
        if self.history_window:
            self.history_window.refresh()
            self.history_window.show()
            self.history_window.raise_()
            self.history_window.activateWindow()

    @Slot()
    def _on_quit(self):
        if self._state == AppState.RECORDING:
            self.recorder.stop_recording()
        if self._state in (AppState.READY, AppState.LOADING, AppState.TRANSCRIBING):
            self.daemon_manager.stop()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
