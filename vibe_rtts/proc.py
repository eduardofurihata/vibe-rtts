"""Small helpers around QProcess.

Kept dependency-free (only PySide6) so both the daemon manager and the audio
recorder can use it without importing each other.
"""

import sys

from PySide6.QtCore import QProcess


def run_detached(program: str, arguments: list[str], label: str) -> bool:
    """Fire and forget a helper process, without leaving a zombie behind.

    subprocess.Popen is never reaped unless someone waits on it, so every clipboard
    copy and every paste used to leave a defunct process attached to the app. Qt
    reaps detached children itself.
    """
    ok, _pid = QProcess.startDetached(program, arguments)
    if not ok:
        print(f"[{label}] could not start {program}", flush=True)
    return ok


def copy_to_clipboard(text: str, label: str) -> bool:
    """Put text on the system clipboard.

    On Wayland Qt only owns the clipboard while one of its windows has focus, and
    a tray app never has it, so Linux goes through wl-copy. On macOS QClipboard
    writes straight to NSPasteboard, which keeps the text after we lose focus —
    no helper process, and no locale to get wrong (pbcopy mangles accents when
    the app starts without LANG, as it does from Finder).
    """
    if sys.platform != "darwin":
        return run_detached("wl-copy", [text], label)
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText(text)
    return True


class StderrTail:
    """Keeps the last stderr lines of a QProcess, so a failure can be explained.

    A process that dies only tells us the exit code; the reason is in stderr.
    Attach one of these to a QProcess and `text()` gives you something to put in
    a notification instead of "exit code 1".
    """

    def __init__(self, process: QProcess, label: str, keep: int = 5):
        self._label = label
        self._keep = keep
        self._lines: list[str] = []
        process.readyReadStandardError.connect(
            lambda: self._collect(process.readAllStandardError().data())
        )

    def _collect(self, raw: bytes):
        data = raw.decode(errors="replace")
        print(f"[{self._label}] {data.rstrip()}", flush=True)
        self._lines.extend(line.strip() for line in data.splitlines() if line.strip())
        del self._lines[:-self._keep]

    def text(self) -> str:
        return " ".join(self._lines).strip()
