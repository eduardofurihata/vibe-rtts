"""Paste into the focused app on macOS by posting a synthetic ⌘V.

Posting keyboard events needs the Accessibility permission for the process
that runs us (Terminal, or whatever launched the app). Without it CGEventPost
silently drops the events, so we check first and say what to do.
"""

import ctypes
import time

_APP_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

_KVK_ANSI_V = 0x09
_FLAG_COMMAND = 0x00100000           # kCGEventFlagMaskCommand
_HID_EVENT_TAP = 0                   # kCGHIDEventTap
_SOURCE_STATE_PRIVATE = -1           # kCGEventSourceStatePrivate
_UTF8 = 0x08000100                   # kCFStringEncodingUTF8
_AX_TIMEOUT_S = 0.5                  # a hung app must not freeze our GUI thread
_AX_ERROR_NO_VALUE = -25212          # kAXErrorNoValue
_FOCUS_RETRIES = 4
_FOCUS_RETRY_S = 0.1

# Roles that are text inputs by definition. Anything else counts only if it has a
# caret (AXSelectedTextRange) and an editable value — contenteditable in web pages
# and editors shows up that way.
_TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}

_lib = None


def _libs():
    global _lib
    if _lib is None:
        app = ctypes.CDLL(_APP_SERVICES)
        cf = ctypes.CDLL(_CORE_FOUNDATION)
        app.AXIsProcessTrusted.restype = ctypes.c_bool
        app.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        app.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        app.CGEventSourceCreate.restype = ctypes.c_void_p
        app.CGEventSourceCreate.argtypes = [ctypes.c_int32]
        app.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        app.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        app.CGEventSetFlags.restype = None
        app.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        app.CGEventPost.restype = None
        app.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cf.CFRelease.restype = None
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        V = ctypes.c_void_p
        app.AXUIElementCreateApplication.restype = V
        app.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
        app.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
        app.AXUIElementCopyAttributeValue.argtypes = [V, V, ctypes.POINTER(V)]
        app.AXUIElementSetAttributeValue.restype = ctypes.c_int32
        app.AXUIElementSetAttributeValue.argtypes = [V, V, V]
        app.AXUIElementIsAttributeSettable.restype = ctypes.c_int32
        app.AXUIElementIsAttributeSettable.argtypes = [V, V, ctypes.POINTER(ctypes.c_bool)]
        app.AXUIElementSetMessagingTimeout.restype = ctypes.c_int32
        app.AXUIElementSetMessagingTimeout.argtypes = [V, ctypes.c_float]
        cf.CFStringCreateWithCString.restype = V
        cf.CFStringCreateWithCString.argtypes = [V, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [V, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFDictionaryCreate.restype = ctypes.c_void_p
        cf.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
        _lib = (app, cf)
    return _lib


def is_trusted(prompt: bool = False) -> bool:
    """Whether we may post keyboard events. With prompt=True, macOS also opens
    its "allow Accessibility" dialog when we may not."""
    app, cf = _libs()
    if not prompt:
        return app.AXIsProcessTrusted()
    key = ctypes.c_void_p.in_dll(app, "kAXTrustedCheckOptionPrompt")
    true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
    keys = (ctypes.c_void_p * 1)(key.value)
    values = (ctypes.c_void_p * 1)(true.value)
    options = cf.CFDictionaryCreate(
        None, keys, values, 1,
        ctypes.addressof(ctypes.c_byte.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
        ctypes.addressof(ctypes.c_byte.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
    try:
        return app.AXIsProcessTrustedWithOptions(options)
    finally:
        cf.CFRelease(options)


def _frontmost_pid() -> int | None:
    """PID of the app that owns the keyboard focus, from NSWorkspace.

    The system-wide AX element would be the textbook way, but asking it for
    AXFocusedApplication fails (kAXErrorCannotComplete) from here; going by PID
    is what works.
    """
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
    send_int = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
    workspace = send(objc.objc_getClass(b"NSWorkspace"), objc.sel_registerName(b"sharedWorkspace"))
    front = send(workspace, objc.sel_registerName(b"frontmostApplication"))
    if not front:
        return None
    return send_int(front, objc.sel_registerName(b"processIdentifier"))


class _AX:
    """Scoped helper: every CF object it hands out is released on exit."""

    def __init__(self):
        self.app, self.cf = _libs()
        self._owned = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for ref in self._owned:
            if ref:
                self.cf.CFRelease(ref)

    def own(self, ref):
        self._owned.append(ref)
        return ref

    def str(self, text):
        return self.own(self.cf.CFStringCreateWithCString(None, text.encode(), _UTF8))

    def application(self, pid):
        element = self.own(self.app.AXUIElementCreateApplication(pid))
        self.app.AXUIElementSetMessagingTimeout(element, _AX_TIMEOUT_S)
        return element

    def get(self, element, name):
        """(error, value) — value is owned and released on exit."""
        out = ctypes.c_void_p()
        err = self.app.AXUIElementCopyAttributeValue(element, self.str(name), ctypes.byref(out))
        return err, (self.own(out.value) if err == 0 else None)

    def text(self, value):
        buf = ctypes.create_string_buffer(64)
        if value and self.cf.CFStringGetCString(value, buf, len(buf), _UTF8):
            return buf.value.decode()
        return None

    def enable_tree(self, element):
        # Electron apps (Antigravity, Claude, Teams, Slack) only build their
        # accessibility tree when asked to; elsewhere this just fails, harmlessly.
        true = ctypes.c_void_p.in_dll(self.cf, "kCFBooleanTrue")
        self.app.AXUIElementSetAttributeValue(element, self.str("AXManualAccessibility"), true)


def wake_focused_app():
    """Ask the focused app to build its accessibility tree, ahead of time.

    Electron takes a moment to build it the first time. Called when recording
    starts, so by the time the transcription is ready the answer is instant.
    """
    try:
        pid = _frontmost_pid()
        if pid:
            with _AX() as ax:
                ax.enable_tree(ax.application(pid))
    except Exception as e:
        print(f"[PASTE] Could not wake the focused app: {e}", flush=True)


def focused_text_input() -> bool:
    """Whether the keyboard focus is on something that accepts typed text.

    Used to decide if a finished transcription can be pasted on its own: with the
    focus on the Finder, the desktop or a list, a ⌘V would do nothing useful — or
    something unexpected. Any error counts as "no": the text stays on the
    clipboard and ⌃/ / ⌘V still paste it by hand.
    """
    try:
        pid = _frontmost_pid()
        if not pid:
            return False
        with _AX() as ax:
            focused_app = ax.application(pid)
            ax.enable_tree(focused_app)
            element = None
            # An Electron tree that is still being built answers "no value" for a
            # moment; a few short retries cover a wake-up that came too late.
            for attempt in range(_FOCUS_RETRIES):
                err, element = ax.get(focused_app, "AXFocusedUIElement")
                if element or err != _AX_ERROR_NO_VALUE:
                    break
                time.sleep(_FOCUS_RETRY_S)
            if not element:
                print(f"[PASTE] No focused element in pid {pid} (AX error {err})", flush=True)
                return False

            if ax.text(ax.get(element, "AXRole")[1]) in _TEXT_ROLES:
                return True
            if ax.get(element, "AXSelectedTextRange")[0] != 0:
                return False
            settable = ctypes.c_bool(False)
            ax.app.AXUIElementIsAttributeSettable(element, ax.str("AXValue"), ctypes.byref(settable))
            return settable.value
    except Exception as e:
        print(f"[PASTE] Could not inspect the focused element: {e}", flush=True)
        return False


def paste_command_v():
    """Post ⌘V down/up.

    The flags are set explicitly, from a private event source: the user is
    usually still holding Control from ⌃/ or ⌃, when this runs, and inheriting the
    live modifier state would turn it into ⌃⌘V.
    """
    app, cf = _libs()
    source = app.CGEventSourceCreate(_SOURCE_STATE_PRIVATE)
    try:
        for key_down in (True, False):
            event = app.CGEventCreateKeyboardEvent(source, _KVK_ANSI_V, key_down)
            app.CGEventSetFlags(event, _FLAG_COMMAND)
            app.CGEventPost(_HID_EVENT_TAP, event)
            cf.CFRelease(event)
    finally:
        if source:
            cf.CFRelease(source)
