#!/usr/bin/env python3
"""Voice transcription daemon — keeps the Whisper model loaded in GPU memory.

Linux runs faster-whisper on CUDA; macOS (--device mps) runs mlx-whisper on the
Apple GPU, since faster-whisper cannot use Metal.

Listens on a Unix socket. Accepts audio file paths, transcribes, returns text.
Model stays loaded so transcription is near-instant (<1s).

Commands via socket:
  /path/to/audio.wav       → transcribe file, return "lang:text"
  pt:/path/to/audio.wav    → transcribe with forced language, return "pt:text"
  status                   → return "ready"
  device                   → return the device the model is loaded on ("cuda"/"mps"/"cpu")
  shutdown                 → reply "bye" and exit, freeing the GPU memory
"""

import argparse
import ctypes
import os
import signal
import socket
import sys
import threading
import time

import numpy as np

SOCKET_PATH = "/tmp/voice-daemon.sock"

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """Ask the kernel to SIGTERM us when our parent dies.

    Without this, an app that dies without cleanup (crash, SIGKILL) leaves the
    model resident and the GPU memory unavailable. PySide6 exposes no
    QProcess.setChildProcessModifier, so the child arms it for itself.
    """
    if sys.platform == "darwin":
        _watch_parent_macos()
        return
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


def _watch_parent_macos():
    """macOS has no prctl(PR_SET_PDEATHSIG): watch for the reparent instead.

    When our parent dies we are reparented (to launchd, pid 1), so getppid()
    changing is the proof. A 1s poll costs nothing and bounds the leak to a second.
    """
    parent = os.getppid()
    if parent == 1:
        print("Parent already gone before startup. Exiting.", file=sys.stderr, flush=True)
        sys.exit(0)

    def watch():
        while os.getppid() == parent:
            time.sleep(1)
        print("Parent died. Exiting.", file=sys.stderr, flush=True)
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


_FRAME = 480                # 30 ms at 16 kHz
_MIN_SPEECH_S = 0.3         # less than this above the floor is not a sentence
_ABS_FLOOR = 500            # int16 RMS; room noise peaks ~430, speech on the mic 600-2500


def has_speech(audio: np.ndarray) -> bool:
    """Energy gate: is there at least _MIN_SPEECH_S of sound clearly above the room?

    mlx-whisper has no VAD and its no-speech score comes back 0.00 even for pure
    silence, which it happily transcribes as "Thank you." — and auto-paste would
    then type that into the user's document. Speech on the built-in mic sits in
    the thousands (int16 RMS), room noise around a hundred, so an absolute floor
    separates them. Not relative to the clip itself: continuous speech with no
    pauses would then be its own baseline and get thrown away.
    """
    if audio.size < _FRAME:
        return False
    samples = audio.astype(np.float32)
    if np.abs(samples).max() <= 1.0:  # float audio in [-1, 1]
        samples = samples * 32768
    frames = samples[: samples.size // _FRAME * _FRAME].reshape(-1, _FRAME)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return (rms > _ABS_FLOOR).sum() * _FRAME / 16000 >= _MIN_SPEECH_S


def _load_mlx(model_name):
    """Load mlx-whisper on the Apple GPU and return transcribe(path, language).

    mlx-whisper loads lazily on the first call, so the warm-up IS the load: it
    downloads the model on the very first run and fails here — not on the user's
    first dictation — if anything is wrong.
    """
    import mlx_whisper
    from mlx_whisper.audio import load_audio

    def transcribe(audio, language=None):
        if isinstance(audio, str):
            audio = np.array(load_audio(audio), dtype=np.float32)  # mx.array -> numpy
        if not has_speech(audio):
            return "", None  # the app reports "No speech detected"
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=model_name, language=language,
            verbose=None,  # None = no progress bar on stdout
        )
        return result.get("text", "").strip(), result.get("language")

    print("Warming up...", flush=True)
    try:
        # Real noise, not zeros: silence would be stopped by the speech gate and
        # never load the model, which is the whole point of warming up.
        rng = np.random.default_rng(0)
        transcribe(rng.normal(0, 0.3, 16000).astype(np.float32))
    except Exception as e:
        print(f"FATAL: could not load {model_name} with mlx-whisper: {e}",
              file=sys.stderr, flush=True)
        sys.exit(1)
    return transcribe


def main():
    parser = argparse.ArgumentParser(description="Voice transcription daemon")
    parser.add_argument("-m", "--model", default="large-v3")
    parser.add_argument("-d", "--device", default="cuda", choices=["cuda", "mps", "cpu"])
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
    if device == "mps":
        transcribe = _load_mlx(args.model)
    else:
        from faster_whisper import WhisperModel
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

        def transcribe(audio, language=None):
            kwargs = {"beam_size": args.beam_size, "vad_filter": True}
            if language:
                kwargs["language"] = language
            segments, info = model.transcribe(audio, **kwargs)
            return " ".join(seg.text.strip() for seg in segments).strip(), info.language

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

            with lock:
                text, detected = transcribe(path, language)

            # Response format: "detected_lang:transcribed_text"
            detected = detected or "unknown"
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
