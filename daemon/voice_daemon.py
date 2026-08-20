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
import ctypes
import os
import signal
import socket
import sys
import threading

import numpy as np
from faster_whisper import WhisperModel

SOCKET_PATH = "/tmp/voice-daemon.sock"

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """Ask the kernel to SIGTERM us when our parent dies.

    Without this, an app that dies without cleanup (crash, SIGKILL) leaves the
    model resident and the GPU memory unavailable. PySide6 exposes no
    QProcess.setChildProcessModifier, so the child arms it for itself.
    """
    try:
        rc = ctypes.CDLL("libc.so.6", use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception as e:
        print(f"Could not arm parent-death signal: {e}", file=sys.stderr, flush=True)
        return
    if rc != 0:
        print(f"prctl(PR_SET_PDEATHSIG) failed with {rc}: this daemon may outlive its parent",
              file=sys.stderr, flush=True)
        return
    # The parent may have died between fork and prctl, in which case the signal
    # was never queued: check for the reparent-to-init that proves it.
    if os.getppid() == 1:
        print("Parent already gone before startup. Exiting.", file=sys.stderr, flush=True)
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Voice transcription daemon")
    parser.add_argument("-m", "--model", default="large-v3")
    parser.add_argument("-d", "--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("-c", "--compute-type", default="int8")
    parser.add_argument("-b", "--beam-size", type=int, default=5)
    parser.add_argument("--exit-with-parent", action="store_true",
                        help="Die when the process that started us dies, so a crashed "
                             "app never leaves the model holding GPU memory.")
    parser.add_argument("--allow-cpu-fallback", action="store_true",
                        help="Fall back to CPU if CUDA fails. Off by default: on CPU "
                             "large-v3 is too slow to be usable, and a silent "
                             "fallback would look ready while being useless.")
    args = parser.parse_args()

    if args.exit_with_parent:
        _die_with_parent()

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

    # Warm up before announcing readiness, mirroring the production call so the
    # user's first dictation pays nothing extra. The two passes load different
    # things and fail for different reasons, so they get different policies.
    silence = np.zeros(16000, dtype=np.float32)  # 1s at 16kHz
    print("Warming up...", flush=True)

    # Pass 1 — build the Silero VAD (ONNX sessions, lazy behind an lru_cache in
    # faster_whisper). Runs on CPU, so failing here says nothing about the GPU:
    # the first real transcription just pays for it instead.
    try:
        list(model.transcribe(silence, vad_filter=True, beam_size=1)[0])
    except Exception as e:
        print(f"VAD warmup failed (first transcription will be slower): {e}",
              file=sys.stderr, flush=True)

    # Pass 2 — the encoder/decoder with the beam size production uses. This is
    # the real GPU check: WhisperModel() can construct and only blow up here
    # (typically out of memory), and serving a socket that looks ready while
    # inference is broken is worse than not starting.
    try:
        list(model.transcribe(silence, vad_filter=False, beam_size=args.beam_size)[0])
    except Exception as e:
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
