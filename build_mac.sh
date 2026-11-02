#!/bin/bash
# Build My Narrator.app on macOS from the repository root.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then echo "This builder requires macOS."; exit 1; fi
if ! command -v python3 >/dev/null; then echo "Install Python 3 with Tkinter support first."; exit 1; fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "FFmpeg not found. Install it with: brew install ffmpeg"; exit 1
fi
if ! command -v ksay >/dev/null; then
  echo "ksay not found. Ensure Kokoro Say is installed and in PATH."; exit 1
fi
python3 -m venv .build-venv
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
