"""Subtitles the video already has, used as help for the Thai and the translation:

  - caption tracks: YouTube's own captions (downloaded with the video, see fetch.py) and subtitle
    tracks inside a video file (MKV/MP4 soft subtitles);
  - subtitles burned into the picture, read from frames with macOS's text recognition (ocr.swift).

Each becomes a helper with timed lines: Thai → the original, English or Chinese → a translation.
"""
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from . import captions, models, paths

SRC = Path(__file__).with_name("ocr.swift")
BIN = models.CACHE.parent / "bin" / "ocr"
EVERY = 0.75             # seconds between frames: subtitles stay up at least a second
BAND = (0.55, 1.0)       # where burned-in subtitles sit: the lower part of the picture
THAI = re.compile(r"[฀-๿]")
CJK = re.compile(r"[㐀-鿿]")


def _binary():
    if not BIN.exists() or BIN.stat().st_mtime < SRC.stat().st_mtime:
        BIN.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(["swiftc", "-O", "-o", str(BIN), str(SRC)], capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError("Couldn't build the subtitle reader (needs Xcode's command-line tools). " + p.stderr[-300:])
    return BIN


def script_of(text):
    if THAI.search(text):
        return "th"
    if CJK.search(text):
        return "zh"
    return "en" if re.search(r"[A-Za-z]{2,}", text) else None


def _same(a, b):
    return a == b or SequenceMatcher(None, a, b).ratio() > 0.82


def read_picture(video, duration, on_progress=None, every=EVERY, band=BAND):
    """{"th": [cues], "en": [...], "zh": [...]} from subtitles burned into the picture."""
    p = subprocess.Popen([str(_binary()), str(video), str(every), str(band[0]), str(band[1])],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    frames = []
    for line in p.stdout:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "t" in d:
            frames.append(d)
            if on_progress and duration and len(frames) % 20 == 0:
                on_progress(min(1.0, d["t"] / duration))
        elif d.get("error"):
            raise RuntimeError(d["error"])
    p.wait()
    return cues_from_frames(frames, every)


def cues_from_frames(frames, every=EVERY):
    # per frame and script: the lines joined top to bottom
    per = []
    for f in frames:
        by = {}
        for ln in sorted(f["lines"], key=lambda x: x["y"]):
            text = ln["text"].strip()
            sc = script_of(text)
            if sc and ln.get("conf", 1) >= 0.3 and len(text) >= 2:
                by.setdefault(sc, []).append(text)
        per.append((f["t"], {k: " ".join(v) for k, v in by.items()}))
    out = {}
    n = max(1, len(per))
    for sc in ("th", "en", "zh"):
        seq = [(t, d.get(sc)) for t, d in per]
        # text on screen the whole time (a logo, a show title) isn't a subtitle
        counts = {}
        for _, x in seq:
            if x:
                counts[x] = counts.get(x, 0) + 1
        static = {x for x, c in counts.items() if c > 0.25 * n}
        cues, cur = [], None
        for t, x in seq:
            x = None if (x in static) else x
            if cur and x and _same(cur["variants"][-1], x):
                cur["end"] = t + every
                cur["variants"].append(x)
                continue
            if cur:
                cues.append(cur)
            cur = {"start": t, "end": t + every, "variants": [x]} if x else None
        if cur:
            cues.append(cur)
        result = []
        for c in cues:
            best = max(set(c["variants"]), key=c["variants"].count)     # the reading seen most often
            if c["end"] - c["start"] >= 0.7 or len(c["variants"]) > 1:
                result.append({"start": round(c["start"], 2), "end": round(c["end"], 2), "text": best})
        if len(result) >= 3:
            out[sc] = result
    return out


def tracks_in_file(video, folder):
    """Subtitle tracks inside a video file -> {lang: [cues]} (Thai, English, Chinese)."""
    p = subprocess.run([paths.ffprobe(), "-v", "error", "-select_streams", "s", "-show_entries",
                        "stream=index:stream_tags=language,title", "-of", "json", str(video)], capture_output=True, text=True)
    try:
        streams = json.loads(p.stdout).get("streams") or []
    except ValueError:
        return {}
    out = {}
    for s in streams:
        lang = ((s.get("tags") or {}).get("language") or "").lower()
        title = ((s.get("tags") or {}).get("title") or "").lower()
        key = "th" if lang in ("th", "tha") or "thai" in title else \
              "zh" if lang in ("zh", "chi", "zho") or "chinese" in title or "中" in title else \
              "en" if lang in ("en", "eng") or "english" in title else None
        if not key or key in out:
            continue
        srt = Path(folder) / f"track_{s['index']}.srt"
        r = subprocess.run([paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                            "-map", f"0:{s['index']}", str(srt)], capture_output=True, text=True)
        if r.returncode == 0 and srt.exists():
            cues = captions.parse_srt(srt.read_text(encoding="utf-8", errors="replace"))
            if cues:
                out[key] = cues
    return out


LABELS = {"th": "Thai", "en": "English", "zh": "中文"}


def helper_for(lang, cues, where):
    """A helper (see jobs.add_helper) from timed cues."""
    return {"kind": "original" if lang == "th" else "translation",
            "label": f"{where} ({LABELS[lang]})",
            "text": "\n".join(f"{c['start']:.1f}-{c['end']:.1f} {c['text']}" for c in cues),
            "items": [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues]}
