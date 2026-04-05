import socket

from PySide6.QtCore import QThread, Signal

from vibe_rtts.config import SOCKET_PATH


class TranscribeWorker(QThread):
    finished = Signal(str, str)  # text, language
    error = Signal(str)

    def __init__(self, wav_path: str, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path

    def run(self):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(str(SOCKET_PATH))
            sock.sendall(self.wav_path.encode() + b"\n")

            # Read full response
            chunks = []
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
            sock.close()

            response = b"".join(chunks).decode().strip()

            if not response:
                self.error.emit("No speech detected")
                return

            if response.startswith("ERROR:"):
                self.error.emit(response)
                return

            # Parse "lang:text" format
            if ":" in response and not response.startswith("/"):
                language, text = response.split(":", 1)
            else:
                language = "unknown"
                text = response

            text = text.strip()
            if text:
                self.finished.emit(text, language)
            else:
                self.error.emit("No speech detected")

        except socket.timeout:
            self.error.emit("Transcription timed out (30s)")
        except Exception as e:
            self.error.emit(str(e))
