"""Small helpers around QProcess.

Kept dependency-free (only PySide6) so both the daemon manager and the audio
recorder can use it without importing each other.
"""

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
