#!/usr/bin/env python3
"""My Narrator local audiobook converter. Requires ksay and ffmpeg on PATH.
Usage: python3 convert_book.py exported-book.txt --voice god-guided
"""
import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

VOICES = {
    "michael": "am_michael", "heart": "af_heart",
    "george": "bm_george", "isabella": "bf_isabella",
    "god-guided": "am_onyx",
}

def run(args):
    subprocess.run(args, check=True)

def split_passage(text, limit=550):
    sentences = re.split(r"(?<=[.!?])\\s+", re.sub(r"\\s+", " ", text).strip())
    pieces, buf = [], ""
    for sentence in sentences:
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut < 100: cut = limit
            if buf: pieces.append(buf); buf = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence: continue
        if len(buf) + len(sentence) + 1 > limit:
            if buf: pieces.append(buf)
            buf = sentence
        else:
            buf = (buf + " " + sentence).strip()
    if buf: pieces.append(buf)
    return pieces

def main():
    parser = argparse.ArgumentParser(description="Convert an exported My Narrator book to MP3 using local Kokoro.")
    parser.add_argument("book", type=Path)
    parser.add_argument("--voice", choices=VOICES, default="michael")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for executable in ("ksay", "ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            sys.exit(f"Missing {executable}. Install it first.")
    raw = args.book.read_text(encoding="utf-8-sig")
    if raw.startswith("MY_NARRATOR_EXPORT\n"):
        raw = raw.split("\n", 2)[2]
    pieces = split_passage(raw)
    if not pieces: sys.exit("No readable text found.")
    target = args.output or args.book.with_name(args.book.stem + "-" + args.voice + ".mp3")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="my-narrator-") as temp:
        temp = Path(temp)
        files = []
        for i, passage in enumerate(pieces, 1):
            print(f"Generating segment {i}/{len(pieces)}...", flush=True)
            original = temp / f"raw-{i:05}.mp3"
            processed = temp / f"part-{i:05}.mp3"
            run(["ksay", "-v", VOICES[args.voice], "-s", "0.92" if args.voice == "god-guided" else "1.0", passage, "-o", str(original)])
            if args.voice == "god-guided":
                probe = subprocess.check_output(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=sample_rate","-of","default=noprint_wrappers=1:nokey=1",str(original)],text=True).strip()
                sr = int(probe)
                # Original V6 chain: warm pitch, V5 archival processing, V6 hiss layer.
                filtergraph = (
                    f"[0:a]asetrate={sr}*0.94,aresample={sr},highpass=f=65,bass=g=2:f=140,"
                    "lowpass=f=8500,loudnorm=I=-18:TP=-2:LRA=9,"
                    "highpass=f=300,lowpass=f=3000,equalizer=f=1600:t=q:w=1:g=5,"
                    "acompressor=threshold=0.09:ratio=4:attack=5:release=130:makeup=1.5,"
                    "asoftclip=type=tanh:threshold=0.3,volume=0.85[voice];"
                    "[1:a]highpass=f=350,lowpass=f=3500,volume=0.12[hiss1];"
                    "[voice][hiss1]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[archive];"
                    "[2:a]highpass=f=450,lowpass=f=6500,volume=0.30[hiss2];"
                    "[archive][hiss2]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]"
                )
                run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(original),
                     "-f","lavfi","-i","anoisesrc=color=pink:amplitude=0.012:sample_rate=44100",
                     "-f","lavfi","-i","anoisesrc=color=pink:amplitude=0.045:sample_rate=44100",
                     "-filter_complex",filtergraph,"-map","[out]","-ar","44100",
                     "-c:a","libmp3lame","-b:a","192k",str(processed)])
            else:
                run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(original),
                     "-ar","44100","-c:a","libmp3lame","-b:a","192k",str(processed)])
            files.append(processed)
        playlist = temp / "parts.txt"
        playlist.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in files))
        run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0",
             "-i",str(playlist),"-c","copy",str(target)])
    print(f"Saved: {target}")

if __name__ == "__main__":
    main()
