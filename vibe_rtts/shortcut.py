import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal

from vibe_rtts.config import (
    SHORTCUT_COMPONENT,
    SHORTCUT_TOGGLE_ACTION,
    SHORTCUT_TOGGLE_KEYS,
    SHORTCUT_TOGGLE_DISPLAY,
    SHORTCUT_PASTE_ACTION,
    SHORTCUT_PASTE_KEYS,
    SHORTCUT_PASTE_DISPLAY,
)

# KGlobalAccel setShortcut flags (KGlobalShortcutInfo::SetShortcutFlag)
# SetPresent (0x2)     = the shortcut should be active right now
# NoAutoloading (0x4)  = use the provided value, do NOT load from config file
_SET_FLAGS = 0x2 | 0x4

_COMPONENT_PATH = f"/component/{SHORTCUT_COMPONENT.replace('-', '_')}"

_ACTIONS = [
    {
        "id": [SHORTCUT_COMPONENT, SHORTCUT_TOGGLE_ACTION,
               "Vibe RTTS", "Toggle Recording"],
        "keys": SHORTCUT_TOGGLE_KEYS,
        "display": SHORTCUT_TOGGLE_DISPLAY,
    },
    {
        "id": [SHORTCUT_COMPONENT, SHORTCUT_PASTE_ACTION,
               "Vibe RTTS", "Paste Transcription"],
        "keys": SHORTCUT_PASTE_KEYS,
        "display": SHORTCUT_PASTE_DISPLAY,
    },
]


class ShortcutHandler(QObject):
    """KDE global shortcut registration + listener.

    Registration is done via `dbus-send` subprocess calls because PySide6's
    QDBusMessage can't express `ai` (array of int32) — it sends `av` instead.

    Signal listening is done via a `dbus-monitor` subprocess scoped to our
    component's object path. The monitor parses the shortcut name from the
    signal arguments to distinguish toggle vs paste actions.
    """

    shortcut_activated = Signal()
    paste_activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._register_all_actions()
        self._start_dbus_monitor_listener()

    def _register_all_actions(self):
        """Register all actions and set their shortcuts via dbus-send."""
        for action in _ACTIONS:
            action_id_arg = "array:string:" + ",".join(action["id"])
            keys_csv = ",".join(str(k) for k in action["keys"])

            result = subprocess.run(
                [
                    "dbus-send", "--session", "--print-reply",
                    "--dest=org.kde.kglobalaccel", "/kglobalaccel",
                    "org.kde.KGlobalAccel.doRegister",
                    action_id_arg,
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(
                    f"[SHORTCUT] doRegister({action['id'][1]}) failed: "
                    f"{result.stderr.strip()}", flush=True,
                )
                continue

            result = subprocess.run(
                [
                    "dbus-send", "--session", "--print-reply",
                    "--dest=org.kde.kglobalaccel", "/kglobalaccel",
                    "org.kde.KGlobalAccel.setShortcut",
                    action_id_arg,
                    f"array:int32:{keys_csv}",
                    f"uint32:{_SET_FLAGS}",
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(
                    f"[SHORTCUT] setShortcut({action['id'][1]}) failed: "
                    f"{result.stderr.strip()}", flush=True,
                )
                continue

            keys_hex = ", ".join(f"0x{k:08x}" for k in action["keys"])
            print(
                f"[SHORTCUT] Registered {action['display']} "
                f"({action['id'][1]}  keys=[{keys_hex}])",
                flush=True,
            )

        self._registered = True

    def _start_dbus_monitor_listener(self):
        """Listen for globalShortcutPressed signals from our component.

        Parses the second string argument (shortcut name) from the dbus-monitor
        output to route to the correct signal (toggle vs paste).
        """
        match_rule = (
            "type='signal',"
            f"path='{_COMPONENT_PATH}',"
            "interface='org.kde.kglobalaccel.Component',"
            "member='globalShortcutPressed'"
        )

        def monitor():
            proc = subprocess.Popen(
                ["dbus-monitor", "--session", match_rule],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            last_toggle = 0.0
            last_paste = 0.0
            in_signal = False
            string_count = 0

            for line in proc.stdout:
                if "member=globalShortcutPressed" in line:
                    in_signal = True
                    string_count = 0
                    continue

                if not in_signal:
                    continue

                stripped = line.strip()

                if stripped.startswith("string ") and '"' in stripped:
                    string_count += 1
                    if string_count == 2:
                        # Second string arg = shortcut name
                        action_name = stripped.split('"')[1]
                        in_signal = False
                        now = time.monotonic()

                        if action_name == SHORTCUT_TOGGLE_ACTION:
                            if now - last_toggle > 0.3:
                                last_toggle = now
                                print("[SHORTCUT] toggle fired", flush=True)
                                self.shortcut_activated.emit()

                        elif action_name == SHORTCUT_PASTE_ACTION:
                            if now - last_paste > 0.5:
                                last_paste = now
                                print("[SHORTCUT] paste fired", flush=True)
                                self.paste_activated.emit()

                elif not stripped.startswith("string "):
                    # Non-string line means we missed the args; reset
                    in_signal = False

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        print(f"[SHORTCUT] Listening on {_COMPONENT_PATH}", flush=True)

    def cleanup(self):
        """Unbind all shortcut keys so they return to normal behavior.

        Sets each action's keys to [0] (no key) via setShortcut, which
        removes the KWin key grabs. On next startup, _register_all_actions
        will re-set the proper keys.
        """
        for action in _ACTIONS:
            action_id_arg = "array:string:" + ",".join(action["id"])
            subprocess.run(
                [
                    "dbus-send", "--session", "--print-reply",
                    "--dest=org.kde.kglobalaccel", "/kglobalaccel",
                    "org.kde.KGlobalAccel.setShortcut",
                    action_id_arg,
                    "array:int32:0",
                    f"uint32:{_SET_FLAGS}",
                ],
                capture_output=True, text=True,
            )
        print("[SHORTCUT] Keys unbound (restored to normal)", flush=True)
