# My Narrator
A free, personal-use PDF/EPUB text-to-speech web app.

## Deploy with GitHub Pages
1. Create a new **public** GitHub repository (for example `my-narrator`).
2. Upload all files in this folder to the repository root.
3. In repository Settings > Pages, choose **Deploy from a branch**, `main`, `/ (root)`, and Save.
4. Open the published URL on iPhone Safari. Tap Share > Add to Home Screen.
5. Import a DRM-free EPUB or text-based PDF, select a voice, and tap Play.

## Limitations
- GitHub Pages serves the *app code* publicly, but books imported into the app remain in your own browser's IndexedDB, not on GitHub. Don't commit personal books to the repository.
- The app uses free system speech synthesis; voice quality and background playback depend on browser and iOS. Locking the screen may stop narration.
- No scanned-PDF OCR, DRM bypass, cloud sync, or guaranteed offline support for first launch. PDF.js and JSZip load from a CDN and require internet when not cached.
- Clearing browser website data can delete saved books and progress. Keep original book files.
- Very large books can consume significant local browser storage.
