#!/usr/bin/env python3
"""Voice transcription daemon — keeps faster-whisper model loaded in GPU memory.

Listens on a Unix socket. Accepts audio file paths, transcribes, returns text.
Model stays loaded so transcription is near-instant (<1s).

Commands via socket:
  /path/to/audio.wav       → transcribe file, return "lang:text"
  pt:/path/to/audio.wav    → transcribe with forced language, return "pt:text"
  status                   → return "ready"
  device                   → return the device the model is loaded on ("cuda"/"cpu")
  shutdown                 → reply "bye" and exit, freeing the GPU memory
"""

import argparse
import os
import signal
import socket
import sys
import threading

import numpy as np
from faster_whisper import WhisperModel

SOCKET_PATH = "/tmp/voice-daemon.sock"


def main():
    parser = argparse.ArgumentParser(description="Voice transcription daemon")
    parser.add_argument("-m", "--model", default="large-v3")
    parser.add_argument("-d", "--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("-c", "--compute-type", default="int8")
    parser.add_argument("-b", "--beam-size", type=int, default=5)
    parser.add_argument("--allow-cpu-fallback", action="store_true",
                        help="Fall back to CPU if CUDA fails. Off by default: on CPU "
                             "large-v3 is too slow to be usable, and a silent "
                             "fallback would look ready while being useless.")
    args = parser.parse_args()

    print(f"Loading {args.model} on {args.device}...", flush=True)
    device = args.device
    try:
        model = WhisperModel(args.model, device=device, compute_type=args.compute_type)
    except Exception as e:
        if device == "cuda" and args.allow_cpu_fallback:
            print(f"GPU failed: {e}. Falling back to CPU.", flush=True)
            device = "cpu"
            model = WhisperModel(args.model, device=device, compute_type="int8")
        else:
            print(f"FATAL: could not load {args.model} on {device}: {e}", file=sys.stderr, flush=True)
            sys.exit(1)

    # Warm up before announcing readiness: the first transcription otherwise pays
    # the CTranslate2/cuDNN kernel JIT cost. 1s of silence at 16kHz is enough.
    print("Warming up...", flush=True)
    try:
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32),
                                       beam_size=1, vad_filter=False)
        list(segments)  # transcribe() is lazy; consume it to actually run inference
    except Exception as e:
        # On CUDA a failing warmup means real transcriptions will fail too (typically
        # OOM): die instead of serving a socket that looks ready. WhisperModel() can
        # succeed and only blow up here, so this is the real GPU check.
        if device == "cuda":
            print(f"FATAL: GPU warmup failed, refusing to serve: {e}",
                  file=sys.stderr, flush=True)
            sys.exit(1)
        print(f"Warmup failed (first transcription will be slower): {e}",
              file=sys.stderr, flush=True)

    print("Model loaded. Ready.", flush=True)

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(2)

    def shutdown():
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        os._exit(0)  # _exit: called from a handler thread, skip other threads' cleanup

    def cleanup(sig, frame):
        shutdown()

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    lock = threading.Lock()

    def handle(conn):
        try:
            data = conn.recv(4096).decode().strip()
            if data == "status":
                conn.sendall(b"ready\n")
                return

            if data == "device":
                conn.sendall(f"{device}\n".encode())
                return

            if data == "shutdown":
                print("Shutdown requested. Exiting.", flush=True)
                conn.sendall(b"bye\n")
                conn.close()
                shutdown()
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
