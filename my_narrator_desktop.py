#!/usr/bin/env python3
"""My Narrator Desktop: local EPUB/PDF -> chapter MP3s and chaptered M4B."""
import os
import hashlib
import time
import signal
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
    """Use real XHTML chapter boundaries when present, with a spine-file fallback."""
    import posixpath
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(x.attrib["full-path"] for x in container.iter() if x.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(opf_path))
        manifest = {x.attrib["id"]: x.attrib["href"] for x in opf.iter()
                    if x.tag.endswith("item") and "href" in x.attrib}
        spine = [x.attrib["idref"] for x in opf.iter() if x.tag.endswith("itemref")]
        chapters = []
        for ref in spine:
            href = manifest.get(ref)
            if not href: continue
            name = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href.split("#")[0]))
            if name not in z.namelist(): continue
            raw = z.read(name).decode("utf-8", errors="replace")
            # EPUB XHTML is often not strict XML. Parse chapter containers as HTML.
            class ChapterParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.depth = 0
                    self.active = False
                    self.heading = False
                    self.heading_words = []
                    self.words = []
                    self.found = []
                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag == "div":
                        if self.active:
                            self.depth += 1
                        elif "chapter" in attrs.get("class", "").split():
                            self.active = True
                            self.depth = 1
                            self.words = []
                            self.heading_words = []
                    if self.active:
                        if tag == "p" and "cn" in attrs.get("class", "").split():
                            self.heading = True
                        if tag in ("p", "div", "br", "li", "h1", "h2"):
                            self.words.append("\n")
                def handle_data(self, data):
                    if self.active:
                        self.words.append(data)
                        if self.heading: self.heading_words.append(data)
                def handle_endtag(self, tag):
                    if not self.active: return
                    if tag == "p" and self.heading: self.heading = False
                    if tag == "div":
                        self.depth -= 1
                        if self.depth == 0:
                            title = " ".join("".join(self.heading_words).split())
                            content = "".join(self.words).strip()
                            if len(content) >= 30:
                                self.found.append((title, content))
                            self.active = False
            parser = ChapterParser()
            parser.feed(raw)
            if parser.found:
                for title, content in parser.found:
                    chapters.append((title[:90] if title else f"Chapter {len(chapters)+1}", content))
            else:
                parser = TextHTML()
                parser.feed(raw)
                content = parser.get_text()
                if len(content.strip()) >= 30:
                    heading = re.search(r"<(?:h1|h2|title)[^>]*>(.*?)</(?:h1|h2|title)>", raw, re.I | re.S)
                    title = re.sub(r"<[^>]+>", "", heading.group(1)).strip() if heading else ""
                    label = re.sub(r"\s+", " ", title)[:75] if title else f"Section {len(chapters)+1}"
                    chapters.append((label, content))
        return chapters

def extract_pdf(path):
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError("PyMuPDF is missing. Run: python3 -m pip install pymupdf")
    with pymupdf.open(str(path)) as doc:
        toc = [(level, title.strip(), page) for level, title, page in doc.get_toc()
               if 1 <= page <= len(doc) and title.strip()]
        # PDF bookmarks give genuine named chapter starts. Prefer the deepest
        # available level, avoiding parent and child sections overlapping.
        if toc:
            deepest = max(level for level, _, _ in toc)
            entries = [(title, page) for level, title, page in toc if level == deepest]
            # Some PDFs have only a few bookmarks; use them only if meaningful.
            starts = []
            for title, page in entries:
                if not starts or page > starts[-1][1]:
                    starts.append((title, page))
            if len(starts) >= 2:
                chapters = []
                if starts[0][1] > 1:
                    text = "\\n\\n".join(doc[i].get_text(sort=True) for i in range(starts[0][1]-1)).strip()
                    if text: chapters.append((f"Front Matter (pages 1–{starts[0][1]-1})", text))
                for idx, (title, page) in enumerate(starts):
                    end = starts[idx+1][1]-1 if idx+1 < len(starts) else len(doc)
                    text = "\\n\\n".join(doc[i].get_text(sort=True) for i in range(page-1, end)).strip()
                    if text: chapters.append((title, text))
                if chapters: return chapters
        # No usable bookmarks: explicit page ranges, not invented chapter names.
        chapters = []
        for i in range(0, len(doc), 10):
            text = "\\n\\n".join(page.get_text(sort=True) for page in doc[i:i+10]).strip()
            if text: chapters.append((f"Pages {i+1}–{min(i+10, len(doc))}", text))
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

class ConversionCancelled(Exception):
    pass

CANCEL_EVENT = threading.Event()

def run(args):
    if CANCEL_EVENT.is_set():
        raise ConversionCancelled()
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, start_new_session=True)
    try:
        while proc.poll() is None:
            if CANCEL_EVENT.wait(0.15):
                import signal
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise ConversionCancelled()
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args)
    finally:
        if proc.poll() is None: proc.terminate()

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
         "-i", str(playlist), "-c:a", "libmp3lame", "-b:a", "192k", str(destination)])

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

def load_chapters(book):
    return extract_epub(book) if book.suffix.lower() == ".epub" else extract_pdf(book)

def generate(book, voice, output, log, selected=None):
    for executable in ("ksay", "ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"{executable} not found on PATH. See DESKTOP.md.")
    chapters = load_chapters(book)
    if not chapters:
        raise RuntimeError("No readable text found.")
    indices = list(range(len(chapters))) if selected is None else sorted(set(selected))
    if not indices or any(i < 0 or i >= len(chapters) for i in indices):
        raise RuntimeError("Choose at least one valid section.")
    output.mkdir(parents=True, exist_ok=True)
    voice_id, vintage = VOICES[voice]
    # Hash book contents, voice and selected text to isolate cached audio.
    digest = hashlib.sha256(book.read_bytes()).hexdigest()[:16]
    voice_key = hashlib.sha256((voice + repr(VOICES[voice])).encode()).hexdigest()[:10]
    workspace = output / ".my-narrator-cache" / (digest + "-" + voice_key)
    workspace.mkdir(parents=True, exist_ok=True)
    chapter_dir = output / "MP3 Chapters" / (book.stem[:55] + " - " + voice.split(" — ")[0])
    chapter_dir.mkdir(parents=True, exist_ok=True)
    work = [(i, chapters[i][0], chunks(chapters[i][1])) for i in indices]
    total = sum(len(pieces) for _, _, pieces in work)
    done = 0
    start = time.monotonic()
    chapter_mp3s, labels = [], []
    for i, label, pieces in work:
        if CANCEL_EVENT.is_set(): raise ConversionCancelled()
        if not pieces: continue
        section_key = hashlib.sha256((label + chapters[i][1]).encode()).hexdigest()[:12]
        section_cache = workspace / f"{i+1:04d}-{section_key}"
        section_cache.mkdir(exist_ok=True)
        audio_segments = []
        for j, passage in enumerate(pieces, 1):
            if CANCEL_EVENT.is_set(): raise ConversionCancelled()
            segment = section_cache / f"{j:05d}.mp3"
            if not segment.is_file() or segment.stat().st_size == 0:
                raw = section_cache / f"raw-{j:05d}.mp3"
                pending = section_cache / f"pending-{j:05d}.mp3"
                try:
                    run(["ksay", "-v", voice_id, "-s", "0.92" if vintage else "1.0",
                         passage, "-o", str(raw)])
                    encode_segment(raw, pending, vintage)
                    if CANCEL_EVENT.is_set(): raise ConversionCancelled()
                    os.replace(pending, segment)
                finally:
                    raw.unlink(missing_ok=True)
                    pending.unlink(missing_ok=True)
            audio_segments.append(segment)
            done += 1
            elapsed = time.monotonic() - start
            remaining = int(elapsed / done * (total - done)) if done else 0
            log(f"Audio: {done}/{total} ({done/total:.0%}) · approx. {remaining//60}m {remaining%60}s remaining")
        dest = chapter_dir / f"{i+1:03d} - {re.sub(r'[^a-zA-Z0-9 _-]', '', label)[:60]}.mp3"
        if CANCEL_EVENT.is_set(): raise ConversionCancelled()
        # Assemble from cached segments; completed chapters are reusable on resume.
        temp_dest = section_cache / "chapter-pending.mp3"
        try:
            concat_mp3(audio_segments, temp_dest, section_cache)
            if CANCEL_EVENT.is_set(): raise ConversionCancelled()
            os.replace(temp_dest, dest)
        finally:
            temp_dest.unlink(missing_ok=True)
        chapter_mp3s.append(dest)
        labels.append(label)
    if not chapter_mp3s:
        raise RuntimeError("No audio chapters were generated.")
    selection_key = hashlib.sha256(",".join(map(str, indices)).encode()).hexdigest()[:8]
    m4b = output / f"{book.stem} - {voice.split(' — ')[0]} - {selection_key}.m4b"
    log("Packaging chaptered M4B...")
    with tempfile.TemporaryDirectory(prefix="my-narrator-package-") as directory:
        pending = Path(directory) / "book.m4b"
        make_m4b(chapter_mp3s, labels, pending, Path(directory))
        if CANCEL_EVENT.is_set(): raise ConversionCancelled()
        os.replace(pending, m4b)
    log(f"COMPLETE: {m4b}")
    return m4b

BIBLE_BOOKS = """Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|1 Samuel|2 Samuel|1 Kings|2 Kings|1 Chronicles|2 Chronicles|Ezra|Nehemiah|Esther|Job|Psalms|Proverbs|Ecclesiastes|Song of Songs|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|1 Corinthians|2 Corinthians|Galatians|Ephesians|Philippians|Colossians|1 Thessalonians|2 Thessalonians|1 Timothy|2 Timothy|Titus|Philemon|Hebrews|James|1 Peter|2 Peter|1 John|2 John|3 John|Jude|Revelation""".split("|")

def bible_location(label):
    """Classify explicitly named Bible chapters, without guessing other material."""
    label = " ".join(label.split())
    if re.match(r"^Psalm\s+\d+\b", label, re.I):
        return ("Old Testament", "Psalms")
    for index, name in enumerate(BIBLE_BOOKS):
        if re.match(r"^" + re.escape(name) + r"\s+(\d+)(?:\b|$)", label, re.I):
            return ("Old Testament" if index < 39 else "New Testament", name)
    return ("Additional Material", "Other Sections")

class App:
    def __init__(self, root):
        self.root = root
        root.title("My Narrator — Audiobook Studio")
        root.geometry("740x680")
        root.minsize(620, 570)
        self.book = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.home() / "Music" / "My Narrator"))
        self.voice = tk.StringVar(value="Michael — American male")
        self.messages = queue.Queue()
        self.cancel_event = CANCEL_EVENT
        self.loaded_book = None
        self.chapters = []
        self.tree_items = {}
        self.player_proc = None
        self.player_paused = False
        self.preview_path = None
        # Scroll the entire studio so playback and conversion controls remain reachable.
        outer = ttk.Frame(root)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        page_scroll = tk.Scrollbar(outer, orient="vertical", command=canvas.yview, width=20,
                                   relief="raised", bg="#8498b5", troughcolor="#e4e9f0",\n                                   activebackground="#54739e")
        canvas.configure(yscrollcommand=page_scroll.set)
        page_scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        # Explicit navigation buttons remain visible even with macOS auto-hidden scrollbars.
        scroll_controls = ttk.Frame(root)
        scroll_controls.pack(side="bottom", fill="x")
        ttk.Button(scroll_controls, text="▲ Scroll up", command=lambda: canvas.yview_scroll(-5, "units")).pack(side="left", padx=8, pady=3)
        ttk.Button(scroll_controls, text="▼ Scroll down", command=lambda: canvas.yview_scroll(5, "units")).pack(side="right", padx=8, pady=3)
        frame = ttk.Frame(canvas, padding=20)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        def wheel(event):
            # Let chapter tree and log text handle their own scrolling.
            widget = event.widget
            if widget is self.sections or widget is self.log_box:
                return
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(-int(delta / abs(delta)), "units")
        root.bind_all("<MouseWheel>", wheel, add="+")
        root.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"), add="+")
        root.bind_all("<Button-5>", lambda e: canvas.yview_scroll(3, "units"), add="+")
        ttk.Label(frame, text="My Narrator", font=("Helvetica", 24, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Generate locally. AirDrop or iCloud to iPhone.").pack(anchor="w", pady=(0, 15))
        ttk.Label(frame, text="PDF or DRM-free EPUB").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(3, 12))
        ttk.Entry(row, textvariable=self.book).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choose Book", command=self.choose_book).pack(side="left", padx=(8, 0))
        ttk.Button(frame, text="Analyze Book / Load Sections", command=self.analyze).pack(fill="x", pady=(0, 6))
        ttk.Label(frame, text="Browse books and chapters (Cmd-click to select multiple chapters)").pack(anchor="w")
        section_frame = ttk.Frame(frame)
        section_frame.pack(fill="both", expand=True, pady=(3, 4))
        self.sections = ttk.Treeview(section_frame, show="tree", selectmode="extended", height=9)
        scrollbar = ttk.Scrollbar(section_frame, orient="vertical", command=self.sections.yview)
        self.sections.configure(yscrollcommand=scrollbar.set)
        self.sections.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 4))
        ttk.Button(actions, text="Select highlighted group", command=self.select_group).pack(side="left")
        ttk.Button(actions, text="Clear selection", command=lambda: self.sections.selection_remove(*self.sections.selection())).pack(side="left", padx=8)
        player = ttk.LabelFrame(frame, text="Desktop Player", padding=8)
        player.pack(fill="x", pady=(5, 8))
        ttk.Label(player, text="Select a chapter above to preview or play its generated MP3.").pack(anchor="w")
        controls = ttk.Frame(player); controls.pack(fill="x", pady=(5, 0))
        ttk.Button(controls, text="Preview Voice", command=self.preview_chapter).pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="Play MP3", command=self.play_chapter).pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="Pause / Resume", command=self.pause_player).pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="Stop", command=self.stop_player).pack(side="left")
        self.player_status = tk.StringVar(value="Ready")
        ttk.Label(player, textvariable=self.player_status).pack(anchor="w", pady=(5, 0))
        self.stats = tk.StringVar(value="Analyze a book to see its sections and estimated workload.")
        ttk.Label(frame, textvariable=self.stats, wraplength=660).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="Narrator").pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.voice, values=list(VOICES), state="readonly").pack(fill="x", pady=(3, 12))
        ttk.Label(frame, text="Save audiobooks to").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(3, 12))
        ttk.Entry(row, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self.choose_output).pack(side="left", padx=(8, 0))
        self.button = ttk.Button(frame, text="Generate MP3 Chapters + iPhone M4B", command=self.start)
        self.button.pack(fill="x", pady=(4, 5))
        self.cancel_button = ttk.Button(frame, text="Cancel Conversion", command=self.cancel, state="disabled")
        self.cancel_button.pack(fill="x", pady=(0, 10))
        self.log_box = tk.Text(frame, height=9, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.drain)
    def choose_book(self):
        name = filedialog.askopenfilename(filetypes=[("Books", "*.epub *.pdf"), ("All files", "*.*")])
        if name:
            self.book.set(name)
            self.loaded_book = None
            self.sections.delete(*self.sections.get_children())
            self.tree_items = {}
            self.stats.set("Click Analyze Book to load sections.")
    def analyze(self):
        book = Path(self.book.get()).expanduser()
        if not book.is_file() or book.suffix.lower() not in (".pdf", ".epub"):
            messagebox.showerror("Select a book", "Choose a valid PDF or EPUB file.")
            return
        try:
            self.chapters = load_chapters(book)
            self.loaded_book = book.resolve()
            self.sections.delete(*self.sections.get_children())
            self.tree_items = {}
            groups = {}
            for i, (label, content) in enumerate(self.chapters):
                testament, book_name = bible_location(label)
                if testament not in groups:
                    groups[testament] = self.sections.insert("", "end", text=testament, open=True)
                key = (testament, book_name)
                if key not in groups:
                    groups[key] = self.sections.insert(groups[testament], "end", text=book_name, open=False)
                item = self.sections.insert(groups[key], "end",
                    text=f"{label} ({len(content.split()):,} words)")
                self.tree_items[item] = i
            total = sum(len(chunks(text)) for _, text in self.chapters)
            self.stats.set(f"{len(self.chapters)} sections · {total:,} estimated audio segments. Select sections below.")
            if self.chapters and self.tree_items:
                self.sections.selection_set(next(iter(self.tree_items)))
        except Exception as e:
            messagebox.showerror("Could not analyze book", str(e))

    def select_group(self):
        selected = self.sections.selection()
        leaves = []
        def collect(item):
            if item in self.tree_items:
                leaves.append(item)
            for child in self.sections.get_children(item):
                collect(child)
        for item in selected:
            collect(item)
        if leaves:
            self.sections.selection_set(leaves)
            self.stats.set(f"Selected {len(leaves)} chapter/section entries.")

    def selected_chapter(self):
        for item in self.sections.selection():
            if item in self.tree_items:
                return self.tree_items[item]
        messagebox.showinfo("Choose a chapter", "Expand a book and select a chapter first.")
        return None

    def stop_player(self):
        if self.player_proc is not None:
            try:
                if self.player_proc.poll() is None:
                    if self.player_paused:
                        os.kill(self.player_proc.pid, signal.SIGCONT)
                    self.player_proc.terminate()
            except (ProcessLookupError, OSError):
                pass
        self.player_proc = None
        self.player_paused = False
        self.player_status.set("Stopped")

    def pause_player(self):
        if not self.player_proc or self.player_proc.poll() is not None:
            self.player_status.set("Nothing playing")
            return
        try:
            os.kill(self.player_proc.pid, signal.SIGCONT if self.player_paused else signal.SIGSTOP)
            self.player_paused = not self.player_paused
            self.player_status.set("Paused" if self.player_paused else "Playing")
        except OSError as exc:
            self.player_status.set(str(exc))

    def play_audio(self, path, label):
        if not shutil.which("afplay"):
            messagebox.showerror("Player unavailable", "macOS afplay is not installed.")
            return
        self.stop_player()
        self.player_proc = subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
        self.player_status.set("Playing: " + label)
        self.root.after(400, self.check_player)

    def check_player(self):
        if self.player_proc is None:
            return
        if self.player_proc.poll() is None:
            self.root.after(400, self.check_player)
        else:
            self.player_proc = None
            self.player_paused = False
            self.player_status.set("Playback finished")

    def preview_chapter(self):
        index = self.selected_chapter()
        if index is None: return
        if not shutil.which("ksay"):
            messagebox.showerror("Preview unavailable", "ksay is not installed.")
            return
        if self.button.instate(["disabled"]):
            messagebox.showinfo("Busy", "Wait for conversion to finish before previewing.")
            return
        label, content = self.chapters[index]
        sample = chunks(content)
        if not sample: return
        voice_id, vintage = VOICES[self.voice.get()]
        self.player_status.set("Generating a short voice preview…")
        def worker():
            try:
                preview_dir = Path(tempfile.mkdtemp(prefix="my-narrator-preview-"))
                raw = preview_dir / "raw.mp3"
                output = preview_dir / "preview.mp3"
                subprocess.run(["ksay", "-v", voice_id, "-s", "0.92" if vintage else "1.0",
                                sample[0], "-o", str(raw)], check=True, capture_output=True)
                if vintage:
                    encode_segment(raw, output, True)
                else:
                    output = raw
                self.messages.put(("preview", (str(output), label)))
            except Exception as exc:
                self.messages.put(("player_error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def play_chapter(self):
        index = self.selected_chapter()
        if index is None: return
        book = Path(self.book.get()).expanduser()
        label = self.chapters[index][0]
        folder = Path(self.output.get()).expanduser() / "MP3 Chapters" / (book.stem[:55] + " - " + self.voice.get().split(" — ")[0])
        path = folder / f"{index+1:03d} - {re.sub(r'[^a-zA-Z0-9 _-]', '', label)[:60]}.mp3"
        if not path.is_file():
            messagebox.showinfo("Not converted yet", "This chapter has no saved MP3. Click Preview Voice to hear a sample, or convert the selected chapter first.")
            return
        self.play_audio(path, label)

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
                elif kind == "preview": self.play_audio(Path(msg[0]), msg[1] + " (preview)")
                elif kind == "player_error": self.player_status.set("Preview failed: " + msg)
                elif kind == "done":
                    self.button.config(state="normal")
                    self.cancel_button.config(state="disabled")
                    if msg == "CANCELLED": self.write("Conversion cancelled. Completed chapters may remain in output.")
                    elif msg.startswith("ERROR:"): messagebox.showerror("Conversion failed", msg)
                    else: messagebox.showinfo("Audiobook ready", "Saved your M4B and MP3 chapters.\n\n" + msg)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)
    def close(self):
        self.stop_player()
        self.root.destroy()

    def cancel(self):
        self.cancel_event.set()
        self.cancel_button.config(state="disabled")
        self.write("Stopping conversion...")

    def start(self):
        book = Path(self.book.get()).expanduser()
        if not book.is_file() or book.suffix.lower() not in (".pdf", ".epub"):
            messagebox.showerror("Select a book", "Choose a valid PDF or EPUB file.")
            return
        if self.loaded_book != book.resolve():
            self.analyze()
            if self.loaded_book != book.resolve(): return
        selected = sorted({self.tree_items[item] for item in self.sections.selection() if item in self.tree_items})
        if not selected:
            messagebox.showerror("Select sections", "Select chapters, or highlight a book and click Select highlighted group.")
            return
        selected_count = sum(len(chunks(self.chapters[i][1])) for i in selected)
        self.write(f"Selected {len(selected)} sections, {selected_count:,} segments. Existing segments will be reused.")
        self.cancel_event.clear()
        self.button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.write("Starting audiobook generation...")
        def worker():
            try:
                result = generate(book, self.voice.get(), Path(self.output.get()).expanduser(),
                                  lambda msg: self.messages.put(("log", msg)), selected)
                self.messages.put(("done", str(result)))
            except ConversionCancelled:
                self.messages.put(("done", "CANCELLED"))
            except Exception as e:
                self.messages.put(("done", "ERROR: " + str(e)))
        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()
