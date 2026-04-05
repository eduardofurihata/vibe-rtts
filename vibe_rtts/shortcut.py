from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage

from vibe_rtts.config import SHORTCUT_COMPONENT, SHORTCUT_ACTION, SHORTCUT_KEY_CODE


class ShortcutHandler(QObject):
    shortcut_activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._register_shortcut()

    def _register_shortcut(self):
        bus = QDBusConnection.sessionBus()

        try:
            # Register the action with kglobalaccel
            action_id = [
                SHORTCUT_COMPONENT,
                SHORTCUT_ACTION,
                "Vibe RTTS",
                "Toggle Recording",
            ]

            msg = QDBusMessage.createMethodCall(
                "org.kde.kglobalaccel",
                "/kglobalaccel",
                "org.kde.KGlobalAccel",
                "doRegister",
            )
            msg.setArguments([action_id])
            bus.call(msg)

            # Set the shortcut key
            msg = QDBusMessage.createMethodCall(
                "org.kde.kglobalaccel",
                "/kglobalaccel",
                "org.kde.KGlobalAccel",
                "setShortcut",
            )
            msg.setArguments([action_id, [SHORTCUT_KEY_CODE], 0x2])  # SetPresent
            bus.call(msg)

            # Listen for the globalShortcutPressed signal
            # Component path uses underscores
            component_path = f"/component/{SHORTCUT_COMPONENT.replace('-', '_')}"
            connected = bus.connect(
                "org.kde.kglobalaccel",
                component_path,
                "org.kde.kglobalaccel.Component",
                "globalShortcutPressed",
                self._on_shortcut_pressed,
            )

            if connected:
                self._registered = True
            else:
                # Fallback: try connecting with wildcard path
                connected = bus.connect(
                    "",
                    "",
                    "org.kde.kglobalaccel.Component",
                    "globalShortcutPressed",
                    self._on_shortcut_pressed,
                )
                self._registered = connected

        except Exception as e:
            print(f"Warning: Could not register global shortcut: {e}")
            self._registered = False

    @Slot(str, str)
    def _on_shortcut_pressed(self, component, shortcut, *args):
        # Filter for our component
        if SHORTCUT_COMPONENT in str(component) or SHORTCUT_ACTION in str(shortcut):
            self.shortcut_activated.emit()

    def cleanup(self):
        if not self._registered:
            return
        try:
            bus = QDBusConnection.sessionBus()
            action_id = [
                SHORTCUT_COMPONENT,
                SHORTCUT_ACTION,
                "Vibe RTTS",
                "Toggle Recording",
            ]
            msg = QDBusMessage.createMethodCall(
                "org.kde.kglobalaccel",
                "/kglobalaccel",
                "org.kde.KGlobalAccel",
                "setInactive",
            )
            msg.setArguments([action_id])
            bus.call(msg)
        except Exception:
            pass
