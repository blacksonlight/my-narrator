#!/bin/bash
# Build My Narrator.app on macOS from the repository root.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then echo "This builder requires macOS."; exit 1; fi
PYTHON="/opt/homebrew/bin/python3.12"
if [[ ! -x "$PYTHON" ]]; then echo "Homebrew Python 3.12 not found at $PYTHON"; exit 1; fi
"$PYTHON" -c 'import tkinter as tk; r=tk.Tk(); v=r.tk.call("info","patchlevel"); r.destroy(); print("Tk version:",v); assert tuple(map(int,v.split(".")[:2])) >= (8,6), "Tk 8.6+ required"'
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "FFmpeg not found. Install it with: brew install ffmpeg"; exit 1
fi
if ! command -v ksay >/dev/null; then
  echo "ksay not found. Ensure Kokoro Say is installed and in PATH."; exit 1
fi
"$PYTHON" -m venv .build-venv
source .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "pyinstaller>=6,<7" "pymupdf>=1.24,<2"
python - <<'PY'
import tkinter
print("Tkinter available:", tkinter.TkVersion)
PY
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "My Narrator" --collect-all pymupdf my_narrator_desktop.py
echo
echo "Build complete: $(pwd)/dist/My Narrator.app"
echo "Open it in Finder. If macOS warns about an unsigned app, use Control-click > Open."
echo "The app still requires ksay, ffmpeg and ffprobe installed on this Mac."
