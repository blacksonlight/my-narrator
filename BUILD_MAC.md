# Build My Narrator as a Mac app

**Current state:** A macOS PyInstaller build recipe is provided; the actual .app must be built on a Mac. It is not yet signed, notarized, or end-to-end tested.

## Fastest path

1. On your Mac, download the GitHub repository ZIP using **Code → Download ZIP**, and unzip it.
2. Open Terminal and change to the unzipped project folder (type \`cd \` with a trailing space, then drag the folder into Terminal and press Return).
3. Run:

\`\`\`bash
chmod +x build_mac.sh
./build_mac.sh
\`\`\`

The script creates \`dist/My Narrator.app\`. Drag it into **Applications** if you want. Double-click to open it in the future.

**Requirements:** macOS, Python 3 with Tkinter support, Kokoro Say (\`ksay\`), FFmpeg and FFprobe. The script installs PyMuPDF and PyInstaller into a local virtual environment. The app is not self-contained: it uses your installed Kokoro and FFmpeg binaries and their models.

If the builder cannot find \`ksay\`, check \`which ksay\` and your installation. If Python reports \`No module named _tkinter\`, use a Python installation that includes Tkinter. On Apple Silicon, use an arm64 Python build for best compatibility.

## Using the app

Choose a DRM-free EPUB or text-based PDF, choose a voice, choose the output directory, then Generate. It creates a single chaptered M4B and separate MP3 chapter files. AirDrop the M4B to your iPhone and import it into My Narrator Player or BookPlayer.

## Notes

- On first launch, macOS Gatekeeper may warn because the app is unsigned. Only override that warning for a build you created yourself from code you trust.
- Keep your Mac awake during conversion.
- EPUB sections are treated as chapters. PDF text is grouped in 10-page sections.
- DRM-protected books and image-only scanned PDFs aren't supported.
- Full-book conversion, M4B chapters, and iPhone playback should be tested before relying on the workflow.
