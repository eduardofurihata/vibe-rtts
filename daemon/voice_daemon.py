#!/usr/bin/env python3
"""Voice transcription daemon — keeps faster-whisper model loaded in GPU memory.

Listens on a Unix socket. Accepts audio file paths, transcribes, returns text.
Model stays loaded so transcription is near-instant (<1s).

Commands via socket:
  /path/to/audio.wav       → transcribe file, return "lang:text"
  pt:/path/to/audio.wav    → transcribe with forced language, return "pt:text"
  status                   → return "ready"
"""

import argparse
import os
import signal
import socket
import sys
import threading

from faster_whisper import WhisperModel

SOCKET_PATH = "/tmp/voice-daemon.sock"


def main():
    parser = argparse.ArgumentParser(description="Voice transcription daemon")
    parser.add_argument("-m", "--model", default="large-v3")
    parser.add_argument("-d", "--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("-c", "--compute-type", default="int8")
    parser.add_argument("-b", "--beam-size", type=int, default=5)
    args = parser.parse_args()

    print(f"Loading {args.model} on {args.device}...", flush=True)
    try:
        model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    except Exception as e:
        if args.device == "cuda":
            print(f"GPU failed: {e}. Falling back to CPU.", flush=True)
            model = WhisperModel(args.model, device="cpu", compute_type="int8")
        else:
            raise
    print("Model loaded. Ready.", flush=True)

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(2)

    def cleanup(sig, frame):
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    lock = threading.Lock()

    def handle(conn):
        try:
            data = conn.recv(4096).decode().strip()
            if data == "status":
                conn.sendall(b"ready\n")
                return

            language = None
            path = data
            if ":" in data and not data.startswith("/"):
                language, path = data.split(":", 1)

            if not os.path.exists(path):
                conn.sendall(b"ERROR: file not found\n")
                return

            kwargs = {"beam_size": args.beam_size, "vad_filter": True}
            if language:
                kwargs["language"] = language

            with lock:
                segments, info = model.transcribe(path, **kwargs)
                text = " ".join(seg.text.strip() for seg in segments).strip()

            # Response format: "detected_lang:transcribed_text"
            detected = info.language or "unknown"
            conn.sendall(f"{detected}:{text}\n".encode())
        except Exception as e:
            try:
                conn.sendall(f"ERROR: {e}\n".encode())
            except Exception:
                pass
        finally:
            conn.close()

    print(f"Listening on {SOCKET_PATH}", flush=True)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
