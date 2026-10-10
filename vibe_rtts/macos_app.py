"""macOS application-level tweaks, through the Objective-C runtime (no pyobjc)."""

import ctypes

_ACTIVATION_POLICY_ACCESSORY = 1  # NSApplicationActivationPolicyAccessory


def hide_dock_icon() -> bool:
    """Run as a menu-bar-only app: no Dock icon, no app menu.

    LSUIElement in the bundle's Info.plist cannot do it: the launcher ends in an
    exec of the venv's python, so the running process's main bundle is Python's,
    not ours. Asking NSApp directly works however the app was started (make run
    included). Call after QApplication exists — Qt creates NSApp.
    """
    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            ("objc_msgSend", objc))
        ns_app = send(objc.objc_getClass(b"NSApplication"),
                      objc.sel_registerName(b"sharedApplication"))

        set_policy = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(
            ("objc_msgSend", objc))
        return set_policy(ns_app, objc.sel_registerName(b"setActivationPolicy:"),
                          _ACTIVATION_POLICY_ACCESSORY)
    except Exception as e:
        print(f"[APP] Could not hide the Dock icon: {e}", flush=True)
        return False
