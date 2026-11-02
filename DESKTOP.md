# My Narrator Desktop — Mac first

A local desktop audiobook generator with a graphical interface. Converts DRM-free EPUB and text-based PDF to chapter MP3 files **and** one chaptered M4B for iPhone. Uses four standard Kokoro voices. No subscription or remote upload.

## Mac setup

You already installed Kokoro Say (\`ksay\`) and FFmpeg. Check both:

\`\`\`bash
ksay --help
ffmpeg -version
ffprobe -version
\`\`\`

Install the PDF text extractor using a Python environment (Python 3.11 recommended):

\`\`\`bash
cd ~/Downloads
python3 -m venv narrator-env
source narrator-env/bin/activate
python -m pip install pymupdf
python my_narrator_desktop.py
\`\`\`

Download \`my_narrator_desktop.py\` from this repository into Downloads before running. If \`ksay\` is installed via uv and not found, run \`export PATH="$HOME/.local/bin:$PATH"\` before launching. If your macOS Python doesn't have Tkinter, use a Python distribution with Tk support.

## Using it

1. Choose a DRM-free EPUB or text-based PDF.
2. Click **Analyze Book / Load Sections**, then select one or more sections (Cmd-click for multiple). Choose Michael, Heart, George, or Isabella.
3. Choose an output folder and click **Generate MP3 Chapters + iPhone M4B**.
4. Watch the segment count and estimated time remaining. Click **Cancel Conversion** to stop. Restart the same book, voice and output folder to reuse already generated segments.
5. In Finder, right-click the resulting \`.m4b\` and **Share > AirDrop** to your iPhone, or copy it into **iCloud Drive**.
6. On iPhone, open the transferred file from Files, use Share/Open In to import it into **BookPlayer**. You can also import MP3s into BookPlayer.

The output includes \`MP3 Chapters/\` and a single \`.m4b\` with embedded chapter markers. PDFs are grouped into ten-page sections rather than inferred chapter headings; EPUB sections follow the book's spine order.

## Limitations

- Mac is the first supported/test-targeted platform; Windows packaging has not been built.
- Requires installed \`ksay\`, \`ffmpeg\`, \`ffprobe\`, and \`pymupdf\` for PDFs.
- This is a Python desktop app, not yet a signed/double-clickable macOS .app.
- Start with a short EPUB to validate your local installation. The packaged `.app` is still being debugged.
- EPUB parsing is intentionally basic; complex layouts, images, tables, and footnotes may narrate awkwardly.
- Scanned/image-only PDFs need OCR and DRM-protected books aren't supported.
- BookPlayer is a separate iOS player; files do not sync automatically from this desktop app.
- Very long books take time, storage, and CPU. The output M4B is AAC at 128 kbps.
- Use books you have the rights to process.
