# My Narrator — Local MP3 conversion

Your book stays on your device. The GitHub Pages reader cannot execute Kokoro on your Mac, so this first version exports text for a local converter.

1. In My Narrator, import and open a PDF or DRM-free EPUB. Choose your narrator and click **Download book text for MP3 conversion**.
2. Download `convert_book.py` from the app and put it in your Downloads folder alongside the exported `.txt` book.
3. On your Mac, verify `ksay --help` and `ffmpeg -version` work. If you installed ksay using uv, ensure `~/.local/bin` is on your PATH.
4. In Terminal:
   ```bash
   cd ~/Downloads
   python3 convert_book.py "your-book.txt" --voice michael
   ```
   Substitute the actual exported filename. Valid voices: michael, heart, george, isabella.
5. The MP3 appears next to your exported book. Large books may take a long time and require considerable disk space. The current version outputs a single MP3, not chapter-separated files.


Note: the app's browser voice selector remains separate from these Kokoro MP3 narrator choices. MP3 playback inside the app is planned for the next iteration.
