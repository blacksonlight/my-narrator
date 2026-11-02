#!/usr/bin/env python3
"""My Narrator Desktop: local EPUB/PDF -> chapter MP3s and chaptered M4B."""
import os
import sys
import re
import json
import shutil
import subprocess
import tempfile
import threading
import queue
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Finder launches do not inherit your interactive shell's PATH.
EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"), str(Path.home() / ".cargo" / "bin")]
os.environ["PATH"] = os.pathsep.join(EXTRA_PATHS + [os.environ.get("PATH", "")])

VOICES = {
    "GOD GUIDED — Lost Archive V6": ("am_onyx", True),
    "Michael — American male": ("am_michael", False),
    "Heart — American female": ("af_heart", False),
    "George — British male": ("bm_george", False),
    "Isabella — British female": ("bf_isabella", False),
}

class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav"):
            self.skip += 1
        elif not self.skip and tag in ("p", "div", "h1", "h2", "h3", "br", "li"):
            self.words.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav") and self.skip:
            self.skip -= 1
        elif not self.skip and tag in ("p", "div", "h1", "h2", "h3", "li"):
            self.words.append("\n")
    def handle_data(self, data):
        if not self.skip:
            self.words.append(data)
    def get_text(self):
        return "".join(self.words).strip()

def extract_epub(path):
    import posixpath
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(x.attrib["full-path"] for x in container.iter() if x.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(opf_path))
        manifest = {x.attrib["id"]: x.attrib["href"] for x in opf.iter() if x.tag.endswith("item") and "href" in x.attrib}
        spine = [x.attrib["idref"] for x in opf.iter() if x.tag.endswith("itemref")]
        chapters = []
        for i, ref in enumerate(spine, 1):
            href = manifest.get(ref)
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href.split("#")[0]))
            if name not in z.namelist():
                continue
            parser = TextHTML()
            parser.feed(z.read(name).decode("utf-8", errors="replace"))
            content = parser.get_text()
            if len(content.strip()) >= 30:
                chapters.append((f"Chapter {len(chapters)+1}", content))
        return chapters

def extract_pdf(path):
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError("PyMuPDF is missing. Run: python3 -m pip install pymupdf")
    doc = pymupdf.open(str(path))
    chapters = []
    # Page-based parts are a reliable fallback when PDF headings are not marked.
    for i in range(0, len(doc), 10):
        text = "\n\n".join(page.get_text(sort=True) for page in doc[i:i+10]).strip()
        if text:
            chapters.append((f"Pages {i+1}–{min(i+10, len(doc))}", text))
    return chapters

def chunks(text, limit=480):
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut < 100:
                cut = limit
            if current:
                result.append(current)
                current = ""
            result.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if len(current) + len(sentence) + 1 > limit and current:
            result.append(current)
            current = ""
        current = (current + " " + sentence).strip()
    if current:
        result.append(current)
    return [s for s in result if s]

def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)

def duration_ms(path):
    output = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                      "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True)
    return round(float(output.strip()) * 1000)

def encode_segment(original, dest, vintage):
    if vintage:
        sr = int(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                          "-show_entries", "stream=sample_rate",
                                          "-of", "default=noprint_wrappers=1:nokey=1", str(original)], text=True).strip())
        filters = (f"[0:a]asetrate={sr}*0.94,aresample={sr},highpass=f=65,bass=g=2:f=140,"
                   "lowpass=f=8500,loudnorm=I=-18:TP=-2:LRA=9,"
                   "highpass=f=300,lowpass=f=3000,equalizer=f=1600:t=q:w=1:g=5,"
                   "acompressor=threshold=0.09:ratio=4:attack=5:release=130:makeup=1.5,"
                   "asoftclip=type=tanh:threshold=0.3,volume=0.85[voice];"
                   "[1:a]highpass=f=350,lowpass=f=3500,volume=0.12[hiss1];"
                   "[voice][hiss1]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[archive];"
                   "[2:a]highpass=f=450,lowpass=f=6500,volume=0.30[hiss2];"
                   "[archive][hiss2]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(original),
             "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.012:sample_rate=44100",
             "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.045:sample_rate=44100",
             "-filter_complex", filters, "-map", "[out]", "-ar", "44100",
             "-c:a", "libmp3lame", "-b:a", "192k", str(dest)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(original), "-ar", "44100",
             "-c:a", "libmp3lame", "-b:a", "192k", str(dest)])

def concat_mp3(files, destination, temp):
    playlist = temp / "concat.txt"
    # temp paths are under our control and do not contain newlines.
    playlist.write_text("".join("file '" + str(f).replace("'", "'\\''") + "'\n" for f in files))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(playlist), "-c", "copy", str(destination)])

def make_m4b(mp3s, labels, destination, temp):
    durations = [duration_ms(p) for p in mp3s]
    metadata = [";FFMETADATA1", f"title={destination.stem}"]
    elapsed = 0
    for label, ms in zip(labels, durations):
        safe_label = label.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
        metadata += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={elapsed}",
                     f"END={elapsed+ms}", f"title={safe_label}"]
        elapsed += ms
    meta = temp / "chapters.ffmeta"
    meta.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    combined = temp / "all.mp3"
    concat_mp3(mp3s, combined, temp)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(combined), "-i", str(meta),
         "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destination)])

def generate(book, voice, output, log):
    for executable in ("ksay", "ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"{executable} not found on PATH. See DESKTOP.md.")
    chapters = extract_epub(book) if book.suffix.lower() == ".epub" else extract_pdf(book)
    if not chapters:
        raise RuntimeError("No readable text. Scanned PDFs require OCR; DRM-protected EPUBs aren't supported.")
    output.mkdir(parents=True, exist_ok=True)
    voice_id, vintage = VOICES[voice]
    chapter_dir = output / "MP3 Chapters"
    chapter_dir.mkdir(exist_ok=True)
    chapter_mp3s, labels = [], []
    with tempfile.TemporaryDirectory(prefix="my-narrator-") as directory:
        temp = Path(directory)
        total = sum(len(chunks(t)) for _, t in chapters)
        done = 0
        for n, (label, content) in enumerate(chapters, 1):
            pieces = chunks(content)
            if not pieces:
                continue
            audio_segments = []
            for j, passage in enumerate(pieces, 1):
                original = temp / f"raw-{n:04}-{j:05}.mp3"
                segment = temp / f"seg-{n:04}-{j:05}.mp3"
                run(["ksay", "-v", voice_id, "-s", "0.92" if vintage else "1.0",
                     passage, "-o", str(original)])
                encode_segment(original, segment, vintage)
                audio_segments.append(segment)
                done += 1
                log(f"Generating audio: {done}/{total} segments ({round(done/total*100)}%)")
            dest = chapter_dir / f"{n:03d} - {re.sub(r'[^a-zA-Z0-9 _-]', '', label)[:60]}.mp3"
            concat_mp3(audio_segments, dest, temp)
            chapter_mp3s.append(dest)
            labels.append(label)
        if not chapter_mp3s:
            raise RuntimeError("No audio chapters were generated.")
        m4b = output / f"{book.stem} - {voice.split(' — ')[0]}.m4b"
        log("Packaging chaptered M4B...")
        make_m4b(chapter_mp3s, labels, m4b, temp)
    log(f"COMPLETE: {m4b}")
    return m4b

class App:
    def __init__(self, root):
        self.root = root
        root.title("My Narrator — Audiobook Studio")
        root.geometry("650x490")
        root.minsize(540, 440)
        self.book = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.home() / "Music" / "My Narrator"))
        self.voice = tk.StringVar(value="GOD GUIDED — Lost Archive V6")
        self.messages = queue.Queue()
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="My Narrator", font=("Helvetica", 24, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Generate locally. AirDrop or iCloud to iPhone.").pack(anchor="w", pady=(0, 15))
        ttk.Label(frame, text="PDF or DRM-free EPUB").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(3, 12))
        ttk.Entry(row, textvariable=self.book).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choose Book", command=self.choose_book).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="Narrator").pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.voice, values=list(VOICES), state="readonly").pack(fill="x", pady=(3, 12))
        ttk.Label(frame, text="Save audiobooks to").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(3, 12))
        ttk.Entry(row, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self.choose_output).pack(side="left", padx=(8, 0))
        self.button = ttk.Button(frame, text="Generate MP3 Chapters + iPhone M4B", command=self.start)
        self.button.pack(fill="x", pady=(4, 10))
        self.log_box = tk.Text(frame, height=9, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True)
        root.after(100, self.drain)
    def choose_book(self):
        name = filedialog.askopenfilename(filetypes=[("Books", "*.epub *.pdf"), ("All files", "*.*")])
        if name: self.book.set(name)
    def choose_output(self):
        name = filedialog.askdirectory()
        if name: self.output.set(name)
    def write(self, msg):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")
    def drain(self):
        try:
            while True:
                kind, msg = self.messages.get_nowait()
                if kind == "log": self.write(msg)
                elif kind == "done":
                    self.button.config(state="normal")
                    if msg.startswith("ERROR:"): messagebox.showerror("Conversion failed", msg)
                    else: messagebox.showinfo("Audiobook ready", "Saved your M4B and MP3 chapters.\n\n" + msg)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)
    def start(self):
        book = Path(self.book.get()).expanduser()
        if not book.is_file() or book.suffix.lower() not in (".pdf", ".epub"):
            messagebox.showerror("Select a book", "Choose a valid PDF or EPUB file.")
            return
        self.button.config(state="disabled")
        self.write("Starting audiobook generation...")
        def worker():
            try:
                result = generate(book, self.voice.get(), Path(self.output.get()).expanduser(),
                                  lambda msg: self.messages.put(("log", msg)))
                self.messages.put(("done", str(result)))
            except Exception as e:
                self.messages.put(("done", "ERROR: " + str(e)))
        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()
