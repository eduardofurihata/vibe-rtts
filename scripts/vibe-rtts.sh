#!/bin/bash
# Launcher for vibe-rtts: sets CUDA library paths and runs the app
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VENV="$HOME/GitHub/vibe-whisper-transcriber/.venv"

# Build LD_LIBRARY_PATH from nvidia libs in venv
NVIDIA_LIBS=$(find "$VENV" -path "*/nvidia/*/lib" -type d 2>/dev/null | tr '\n' ':')
export LD_LIBRARY_PATH="${NVIDIA_LIBS%:}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m vibe_rtts "$@"
