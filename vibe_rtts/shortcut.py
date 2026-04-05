import threading

from PySide6.QtCore import QObject, Signal

from vibe_rtts.config import SHORTCUT_COMPONENT, SHORTCUT_ACTION, SHORTCUT_KEY_CODE


class ShortcutHandler(QObject):
    shortcut_activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._register_and_listen()

    def _register_and_listen(self):
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop

            # Register shortcut via dbus
            bus = dbus.SessionBus()
            accel = bus.get_object("org.kde.kglobalaccel", "/kglobalaccel")
            iface = dbus.Interface(accel, "org.kde.KGlobalAccel")

            action_id = [
                SHORTCUT_COMPONENT,
                SHORTCUT_ACTION,
                "Vibe RTTS",
                "Toggle Recording",
            ]
            iface.doRegister(action_id)
            iface.setShortcut(action_id, [SHORTCUT_KEY_CODE], 0x2)

            # Start listening for the signal in a background thread with GLib mainloop
            def listen():
                DBusGMainLoop(set_as_default=True)
                listen_bus = dbus.SessionBus()

                component_path = f"/component/{SHORTCUT_COMPONENT.replace('-', '_')}"

                def on_signal(component, shortcut, timestamp):
                    print(f"[SHORTCUT] Signal: {component}/{shortcut}", flush=True)
                    if SHORTCUT_COMPONENT in str(component) or SHORTCUT_ACTION in str(shortcut):
                        print("[SHORTCUT] Matched! Emitting", flush=True)
                        self.shortcut_activated.emit()

                listen_bus.add_signal_receiver(
                    on_signal,
                    signal_name="globalShortcutPressed",
                    dbus_interface="org.kde.kglobalaccel.Component",
                    path=component_path,
                )

                from gi.repository import GLib
                loop = GLib.MainLoop()
                loop.run()

            thread = threading.Thread(target=listen, daemon=True)
            thread.start()

            self._registered = True
            print("[SHORTCUT] Registration OK, listening for Meta+Shift+V", flush=True)

        except ImportError:
            print("[SHORTCUT] python-dbus not available, trying system python fallback", flush=True)
            self._start_dbus_monitor_fallback()
        except Exception as e:
            print(f"[SHORTCUT] Warning: {e}", flush=True)
            self._start_dbus_monitor_fallback()

    def _start_dbus_monitor_fallback(self):
        """Fallback: use dbus-monitor subprocess to catch shortcut signals."""
        import subprocess
        import time

        def monitor():
            proc = subprocess.Popen(
                ["dbus-monitor", "--session",
                 "type='signal',interface='org.kde.kglobalaccel.Component',"
                 "member='globalShortcutPressed'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            last_emit = 0
            for line in proc.stdout:
                # Only trigger on the signal header line, not individual args
                if "member=globalShortcutPressed" in line:
                    now = time.monotonic()
                    if now - last_emit > 1.0:  # Debounce: 1 second
                        last_emit = now
                        print(f"[SHORTCUT] Detected shortcut press", flush=True)
                        self.shortcut_activated.emit()

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        self._registered = True
        print("[SHORTCUT] Fallback: dbus-monitor listening", flush=True)

    def cleanup(self):
        pass
