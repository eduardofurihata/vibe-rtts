import ctypes
import time

from PySide6.QtCore import QObject, Signal

from vibe_rtts.config import SHORTCUT_TOGGLE_DISPLAY, SHORTCUT_PASTE_DISPLAY

_CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"


def _fourcc(code: bytes) -> int:
    return int.from_bytes(code, "big")


# Carbon constants (Events.h / CarbonEvents.h)
_CONTROL_KEY = 0x1000            # controlKey modifier
_KVK_ANSI_COMMA = 0x2B           # physical key, so the keyboard layout does not matter
_KVK_ANSI_PERIOD = 0x2F
_EVENT_CLASS_KEYBOARD = _fourcc(b"keyb")
_EVENT_HOTKEY_PRESSED = 5
_PARAM_DIRECT_OBJECT = _fourcc(b"----")
_TYPE_EVENT_HOTKEY_ID = _fourcc(b"hkid")
_SIGNATURE = _fourcc(b"vrtt")

_TOGGLE_ID = 1
_PASTE_ID = 2

_HOTKEYS = [
    (_TOGGLE_ID, _KVK_ANSI_COMMA, _CONTROL_KEY, SHORTCUT_TOGGLE_DISPLAY),
    (_PASTE_ID, _KVK_ANSI_PERIOD, _CONTROL_KEY, SHORTCUT_PASTE_DISPLAY),
]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_EventHandlerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


def _load_carbon():
    carbon = ctypes.CDLL(_CARBON)
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.GetApplicationEventTarget.argtypes = []
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p, _EventHandlerProc, ctypes.c_ulong,
        ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    carbon.RemoveEventHandler.restype = ctypes.c_int32
    carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    carbon.UnregisterEventHotKey.restype = ctypes.c_int32
    carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    carbon.GetEventParameter.restype = ctypes.c_int32
    carbon.GetEventParameter.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
    return carbon


class MacShortcutHandler(QObject):
    """macOS global shortcuts via Carbon's RegisterEventHotKey.

    Same contract as the KDE ShortcutHandler (shortcut_activated, paste_activated,
    cleanup), so the tray does not care which one it got. RegisterEventHotKey is
    the one global-hotkey API that needs no Accessibility or Input Monitoring
    permission, and the system swallows the keys, so they never reach the
    focused app. Events arrive on the main run loop — the one Qt drives — so the
    handler can emit directly.
    """

    shortcut_activated = Signal()
    paste_activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._carbon = _load_carbon()
        self._hotkey_refs = []
        self._handler_ref = None
        self._last_toggle = 0.0
        self._last_paste = 0.0
        # Held on the instance: if ctypes' callback object were collected, Carbon
        # would call into freed memory on the next key press.
        self._callback = _EventHandlerProc(self._on_carbon_event)
        self._install_handler()
        self._register_all()

    def _install_handler(self):
        spec = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED)
        ref = ctypes.c_void_p()
        status = self._carbon.InstallEventHandler(
            self._carbon.GetApplicationEventTarget(), self._callback, 1,
            ctypes.byref(spec), None, ctypes.byref(ref))
        if status != 0:
            print(f"[SHORTCUT] InstallEventHandler failed: {status}", flush=True)
            return
        self._handler_ref = ref

    def _register_all(self):
        target = self._carbon.GetApplicationEventTarget()
        for hotkey_id, keycode, modifiers, display in _HOTKEYS:
            ref = ctypes.c_void_p()
            status = self._carbon.RegisterEventHotKey(
                keycode, modifiers, _EventHotKeyID(_SIGNATURE, hotkey_id),
                target, 0, ctypes.byref(ref))
            if status != 0:
                # -9878 (eventHotKeyExistsErr): another app already owns the combo.
                print(f"[SHORTCUT] RegisterEventHotKey({display}) failed: {status}",
                      flush=True)
                continue
            self._hotkey_refs.append(ref)
            print(f"[SHORTCUT] Registered {display}", flush=True)

    def _on_carbon_event(self, _call_ref, event, _user_data):
        hotkey = _EventHotKeyID()
        status = self._carbon.GetEventParameter(
            event, _PARAM_DIRECT_OBJECT, _TYPE_EVENT_HOTKEY_ID, None,
            ctypes.sizeof(hotkey), None, ctypes.byref(hotkey))
        if status == 0 and hotkey.signature == _SIGNATURE:
            self._dispatch(hotkey.id)
        return 0  # noErr

    def _dispatch(self, hotkey_id: int):
        now = time.monotonic()
        if hotkey_id == _TOGGLE_ID:
            if now - self._last_toggle > 0.3:
                self._last_toggle = now
                print("[SHORTCUT] toggle fired", flush=True)
                self.shortcut_activated.emit()
        elif hotkey_id == _PASTE_ID:
            if now - self._last_paste > 0.5:
                self._last_paste = now
                print("[SHORTCUT] paste fired", flush=True)
                self.paste_activated.emit()

    def cleanup(self):
        """Give the keys back to the system. Safe to call more than once."""
        for ref in self._hotkey_refs:
            self._carbon.UnregisterEventHotKey(ref)
        self._hotkey_refs = []
        if self._handler_ref is not None:
            self._carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = None
        print("[SHORTCUT] Keys unbound (restored to normal)", flush=True)
