from enum import Enum, auto

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QSettings, QTimer, Slot

from vibe_rtts.config import (
    APP_NAME, ICONS_DIR, APP_DISPLAY_NAME, AUTO_PASTE_DEFAULT, IS_MACOS, PASTE_HINT,
)
from vibe_rtts.proc import copy_to_clipboard, run_detached


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
            # Its own color: sharing READY's green left no way to tell from the icon
            # whether the text was still being processed or already on the clipboard.
            "transcribing": QIcon(str(ICONS_DIR / "mic-transcribing.png")),
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

        # macOS only: Linux/Wayland gives no safe way to know what has the focus.
        self._settings = QSettings(APP_NAME, APP_NAME)
        self._auto_paste_action = None
        if IS_MACOS:
            self._auto_paste_action = QAction("Auto-paste into text fields", self._menu)
            self._auto_paste_action.setCheckable(True)
            self._auto_paste_action.setChecked(
                self._settings.value("auto_paste", AUTO_PASTE_DEFAULT, type=bool))
            self._auto_paste_action.toggled.connect(
                lambda on: self._settings.setValue("auto_paste", on))
            self._menu.addAction(self._auto_paste_action)

        self._history_action = QAction("History", self._menu)
        self._history_action.triggered.connect(self._on_history)
        self._menu.addAction(self._history_action)

        self._menu.addSeparator()

        self._quit_action = QAction("Quit", self._menu)
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self._update_state(AppState.INACTIVE)

        # Double-click detection (SNI on Wayland sends Trigger, not DoubleClick)
        self._click_timer = QTimer()
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(400)
        self._click_count = 0
        self._click_timer.timeout.connect(self._on_click_timeout)
        self.activated.connect(self._on_activated)

        # Components (set by app after init)
        self.daemon_manager = None
        self.recorder = None
        self.transcriber_cls = None
        self.shortcut_handler = None
        self.history_store = None
        self.history_window = None
        self._transcribe_worker = None
        self._asked_accessibility = False  # macOS: open the permission dialog once

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
        self.recorder.recording_failed.connect(self._on_recording_failed)
        self.shortcut_handler.shortcut_activated.connect(self._on_toggle)
        self.shortcut_handler.paste_activated.connect(self._on_paste)

    # --- Paste (Numpad + on Linux, ⌃. on macOS) ---
    @Slot()
    def _on_paste(self):
        """Paste the clipboard into the focused window."""
        print("[TRAY] Paste shortcut fired", flush=True)
        if IS_MACOS:
            self._paste_macos()
            return
        # ydotool uses raw Linux scancodes: KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_V=47
        # Sequence: Ctrl down, Shift down, V down, V up, Shift up, Ctrl up.
        # The delay lets the Numpad+ key release before we inject Ctrl+Shift+V —
        # a timer instead of a shell sleep, which used to leave a zombie behind.
        QTimer.singleShot(100, lambda: run_detached(
            "ydotool", ["key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"], "TRAY"))

    def _paste_macos(self):
        """Post ⌘V — needs the Accessibility permission, so check it first.

        Without the permission CGEventPost drops the keys without a word; saying so
        (and letting macOS open its dialog, once) beats a paste that never happens.
        """
        from vibe_rtts import paste_macos
        if not paste_macos.is_trusted():
            if not self._asked_accessibility:
                self._asked_accessibility = True
                paste_macos.is_trusted(prompt=True)
            self.showMessage(
                "Vibe RTTS",
                "To paste, allow Vibe RTTS (or your terminal) in System Settings → "
                "Privacy & Security → Accessibility. Meanwhile, ⌘V works.",
                QSystemTrayIcon.MessageIcon.Warning, 6000)
            return
        # Same 100ms as Linux: lets the shortcut keys come up before we inject.
        QTimer.singleShot(100, paste_macos.paste_command_v)

    @property
    def _auto_paste(self) -> bool:
        return bool(self._auto_paste_action and self._auto_paste_action.isChecked())

    def _wake_focused_app(self):
        """Have the focused app build its accessibility tree while we record, so
        the text-field check at the end answers at once (Electron is slow to)."""
        if self._auto_paste:
            from vibe_rtts import paste_macos
            paste_macos.wake_focused_app()

    def _auto_paste_if_text_field(self):
        """Paste the fresh transcription if the cursor is in a text field.

        It is on the clipboard either way, so when the focus is elsewhere nothing
        is lost: ⌃. or ⌘V paste it later. Never prompts for Accessibility here —
        that dialog belongs to an explicit ⌃., not to the end of a dictation.
        """
        from vibe_rtts import paste_macos
        trusted = paste_macos.is_trusted()
        text_field = trusted and paste_macos.focused_text_input()
        print(f"[TRAY] Auto-paste: accessibility={trusted} text_field={text_field}", flush=True)
        if text_field:
            paste_macos.paste_command_v()
            self.showMessage("Vibe RTTS", "Pasted ✓ (also on the clipboard)",
                             QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        self.showMessage("Vibe RTTS", f"Copied! {PASTE_HINT} to paste",
                         QSystemTrayIcon.MessageIcon.Information, 3000)

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
            device = getattr(self.daemon_manager, "device", None)
            suffix = " (CPU — slow)" if device == "cpu" else ""
            self.setToolTip(f"{APP_DISPLAY_NAME} — Ready{suffix}")
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
            self.setIcon(self._icons["transcribing"])
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
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._click_count += 1
            if self._click_count == 1:
                self._click_timer.start()
            elif self._click_count >= 2:
                self._click_timer.stop()
                self._click_count = 0
                self._on_toggle()

    @Slot()
    def _on_click_timeout(self):
        self._click_count = 0

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
            self._wake_focused_app()

        elif self._state == AppState.RECORDING:
            # Leave RECORDING now, not when the wav is ready: from the user's point
            # of view the capture ended the moment they hit the shortcut, and the
            # conversion that follows takes a few hundred milliseconds.
            self._update_state(AppState.TRANSCRIBING)
            self.recorder.stop_recording()
            # _on_recording_stopped / _on_recording_failed take it from here

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
                         QSystemTrayIcon.MessageIcon.Warning, 5000)
        self._update_state(AppState.INACTIVE)

    # --- Recording events ---
    @Slot(str)
    def _on_recording_stopped(self, wav_path):
        if self._state != AppState.TRANSCRIBING:  # the toggle usually got here first
            self._update_state(AppState.TRANSCRIBING)
        from vibe_rtts.transcriber import TranscribeWorker
        worker = TranscribeWorker(wav_path)
        worker.transcribed.connect(self._on_transcription_done)
        worker.failed.connect(self._on_transcription_error)
        # QThread.finished (the real one) fires when the thread has ended — the
        # only moment it is safe to let go of the object.
        worker.finished.connect(self._on_worker_finished)
        self._transcribe_worker = worker
        worker.start()

    @Slot(str)
    def _on_recording_failed(self, reason):
        self.showMessage("Vibe RTTS", reason,
                         QSystemTrayIcon.MessageIcon.Warning, 5000)
        # Whatever went wrong, we must not stay stuck on RECORDING: the toggle
        # would have nothing left to stop. AppState is the source of truth here —
        # asking the daemon would mean a socket round-trip on the GUI thread, and
        # if the engine had died, engine_stopped already moved us to INACTIVE.
        if self._state in (AppState.RECORDING, AppState.TRANSCRIBING):
            self._update_state(AppState.READY)

    @Slot(str, str)
    def _on_transcription_done(self, text, language):
        copy_to_clipboard(text, "TRAY")
        # Save to history
        if self.history_store:
            self.history_store.save(text, language)
        self._update_state(AppState.READY)
        if self._auto_paste:
            # The delay lets the clipboard settle and the ⌃, keys come up; the
            # check-and-paste then decides which notification to show.
            QTimer.singleShot(150, self._auto_paste_if_text_field)
            return
        self.showMessage("Vibe RTTS",
                         f"Copied! {PASTE_HINT} to paste",
                         QSystemTrayIcon.MessageIcon.Information, 3000)

    @Slot(str)
    def _on_transcription_error(self, error_msg):
        self.showMessage("Vibe RTTS", f"Transcription failed: {error_msg}",
                         QSystemTrayIcon.MessageIcon.Warning, 3000)
        self._update_state(AppState.READY)

    @Slot()
    def _on_worker_finished(self):
        self._transcribe_worker = None

    # --- Engine control ---
    @Slot()
    def start_engine(self):
        """Load the model without recording. Used by the menu and by the startup
        preload (config.AUTO_START_ENGINE). No-op unless we are INACTIVE."""
        if self._state != AppState.INACTIVE:
            return
        self._pending_record_after_load = False
        self._update_state(AppState.LOADING)
        self.daemon_manager.start()

    # --- Menu actions ---
    @Slot()
    def _on_engine_toggle(self):
        if self._state == AppState.INACTIVE:
            self.start_engine()
        elif self._state == AppState.READY:
            self.daemon_manager.stop()

    def wait_for_transcription(self, timeout_ms: int = 3000):
        """Let a running transcription finish before we tear the app down."""
        worker = self._transcribe_worker
        if worker is not None and worker.isRunning():
            print("[TRAY] Waiting for the transcription to finish...", flush=True)
            worker.wait(timeout_ms)

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
            self.recorder.abort()  # synchronous: never leave ffmpeg behind
        self.wait_for_transcription()
        if self._state in (AppState.READY, AppState.LOADING, AppState.TRANSCRIBING):
            self.daemon_manager.stop()
        if self.shortcut_handler:
            self.shortcut_handler.cleanup()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
