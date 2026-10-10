#!/bin/bash
# Launcher for vibe-rtts: sets CUDA library paths (Linux) and runs the app
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

if [ "$(uname)" = "Darwin" ]; then
    # macOS: own venv in the project (make setup-mac). Started from Finder or the
    # Dock, PATH lacks Homebrew, and both the recorder and mlx-whisper need ffmpeg.
    VENV="$SCRIPT_DIR/.venv"
    export PATH="/opt/homebrew/bin:/usr/local/bin${PATH:+:$PATH}"
else
    VENV="$HOME/GitHub/vibe-whisper-transcriber/.venv"
    # Build LD_LIBRARY_PATH from nvidia libs in venv
    NVIDIA_LIBS=$(find "$VENV" -path "*/nvidia/*/lib" -type d 2>/dev/null | tr '\n' ':')
    export LD_LIBRARY_PATH="${NVIDIA_LIBS%:}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m vibe_rtts "$@"
