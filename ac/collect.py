"""Collections: clips from any of your videos, gathered under a name, in your order, saved as one video
(or one file per clip). Each clip keeps its own video's captions, people, fonts, emoji and logo; when they're
joined, every clip is fitted to one shape (16:9, or 9:16 for vertical) so different videos go together.

Kept in work/collections/<id>.json: {"id", "name", "created", "updated", "items": [{"id", "jid", "start", "end",
"label", "star"?, "no_music"?}], and while saving: "busy", "label", "progress", "error", "exports"}.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import captions, jobs, media, paths, style

DIR = paths.WORK / "collections"
_lock = threading.RLock()


class CollectionError(jobs.JobError):
    pass


def _path(cid):
    if not re.fullmatch(r"[0-9a-f]{10}", cid or ""):
        raise CollectionError("Unknown collection.")
    return DIR / f"{cid}.json"


def load(cid):
    p = _path(cid)
    if not p.exists():
        raise CollectionError("That collection is gone.")
    return json.loads(p.read_text())


def _save(c):
    DIR.mkdir(parents=True, exist_ok=True)
    c["updated"] = time.time()
    tmp = _path(c["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    tmp.replace(_path(c["id"]))
    return c


def _update(cid, **changes):
    with _lock:
        c = load(cid)
        c.update(changes)
        return _save(c)


def listing():
    out = []
    for f in sorted(DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True) if DIR.exists() else []:
        try:
            c = json.loads(f.read_text())
        except ValueError:
            continue
        items = c.get("items") or []
        out.append({"id": c["id"], "name": c.get("name") or "Collection", "count": len(items), "busy": bool(c.get("busy")),
                    "seconds": round(sum(i["end"] - i["start"] for i in items), 1), "updated": c.get("updated")})
    return out


def create(name):
    name = (name or "").strip()[:80] or "New collection"
    c = {"id": uuid.uuid4().hex[:10], "name": name, "created": time.time(), "items": []}
    with _lock:
        return _save(c)


PLACES = {"top-left": (0.18, 0.09), "top": (0.5, 0.09), "top-right": (0.82, 0.09), "center": (0.5, 0.5),
          "lower": (0.5, 0.72), "bottom-left": (0.18, 0.86), "bottom-right": (0.82, 0.86)}


def _hex(v, alpha=False):
    ok = isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}" + ("([0-9A-Fa-f]{2})?" if alpha else ""), v)
    return v if ok else None


def _where(t, default):
    """place: one of PLACES, or "custom" with the x, y you dragged it to (fractions of the picture)."""
    if t.get("place") == "custom":
        try:
            return {"place": "custom", "x": round(min(0.98, max(0.02, float(t["x"]))), 4), "y": round(min(0.98, max(0.02, float(t["y"]))), 4)}
        except (KeyError, TypeError, ValueError):
            pass
    return {"place": t.get("place") if t.get("place") in PLACES else default}


def _moving(t):
    """Movement (float, wiggle, flip, pulse, spin, fly, across) and how many seconds one round takes."""
    if t.get("motion") in style.MOTIONS:
        return {"motion": t["motion"], "period": round(min(8.0, max(0.5, float(t.get("period") or 2))), 2)}
    return {}


def _xy(t):
    return (t["x"], t["y"]) if t.get("place") == "custom" else PLACES[t["place"]]


def _clean_text(t):
    """Your own text on a clip (or on every clip): {"text", "place", "color", "size", "font", "secs"}; None if empty."""
    if not isinstance(t, dict) or not str(t.get("text") or "").strip():
        return None
    return {"text": str(t["text"]).strip()[:120], **_where(t, "top-left"),
            "color": _hex(t.get("color")) or "#FFFFFF", "outline_color": _hex(t.get("outline_color")) or "#000000",
            "bold": t.get("bold") is not False, "bubble": bool(t.get("bubble")),
            "opacity": round(min(1.0, max(0.1, float(t.get("opacity") or 1))), 2),
            "size": round(min(3.0, max(0.5, float(t.get("size") or 1.3))), 2),
            "font": str(t.get("font") or "")[:60], "secs": max(0.0, min(600.0, float(t.get("secs") or 0))), **_moving(t)}


STANDOUT = ("none", "outline", "shadow", "badge", "circle")


def _clean_logo(l):
    """One of your saved logos on a clip (or every clip): {"image", "place", "w", "secs", "standout"}; None if none."""
    if not isinstance(l, dict) or not l.get("image"):
        return None
    image = re.sub(r"[^0-9A-Za-z_.-]", "", str(l["image"]))[:80]
    if not any(f.suffix.lower() in jobs.LOGO_EXT for f in paths.LOGOS.glob(f"{image}.*")):
        return None
    return {"image": image, **_where(l, "top-right"),
            "w": round(min(0.6, max(0.04, float(l.get("w") or 0.14))), 3),
            "secs": max(0.0, min(600.0, float(l.get("secs") or 0))),
            "standout": l.get("standout") if l.get("standout") in STANDOUT else "none",
            "opacity": round(min(1.0, max(0.1, float(l.get("opacity") or 1))), 2),
            **({"edge_color": _hex(l["edge_color"])} if _hex(l.get("edge_color")) else {}), **_moving(l)}


def _logo_touch(l, a, b):
    """The logo as a touch; its outline or badge in a colour that contrasts with it (a white logo on a dark badge)."""
    x, y = _xy(l)
    tone = next((g["tone"] for g in jobs.logos() if g["id"] == l["image"]), "light")
    light = tone == "light"
    edge = l.get("edge_color")                 # your colour for the outline / badge, else one that contrasts
    return {"kind": "image", "image": l["image"], "x": x, "y": y, "w": l["w"], "opacity": l.get("opacity", 1.0),
            "standout": l["standout"], "edge_color": edge or ("#000000" if light else "#FFFFFF"),
            "plate_color": (edge + "D9") if edge else ("#1D2550D9" if light else "#FFFFFFD9"),
            "motion": l.get("motion"), "period": l.get("period"),
            "start": a, "end": min(b, a + l["secs"]) if l["secs"] else b}


def _text_touch(t, a, b):
    """That text as a touch (style.touch_block) on the clip's own timeline: from its start, for secs (0: all of it)."""
    x, y = _xy(t)
    return {"kind": "bubble" if t.get("bubble") else "text", "text": t["text"], "x": x, "y": y, "size": t["size"],
            "color": t["color"], "font": t["font"], "bold": t.get("bold", True), "outline": 0.1,
            "outline_color": t.get("outline_color", "#000000"), "opacity": t.get("opacity", 1.0),
            "motion": t.get("motion"), "period": t.get("period"),
            "start": a, "end": min(b, a + t["secs"]) if t["secs"] else b}


def _clean_item(i, keep_id=True):
    jid = str(i.get("jid") or "")
    jobs.job_dir(jid)                                # it must be one of your videos
    a, b = max(0.0, float(i["start"])), float(i["end"])
    if b - a < 0.3:
        return None
    return {"id": (str(i.get("id")) if keep_id and i.get("id") else uuid.uuid4().hex[:8])[:12], "jid": jid,
            "start": round(a, 3), "end": round(b, 3), "label": str(i.get("label") or "")[:60],
            **({"star": True} if i.get("star") else {}), **({"no_music": True} if i.get("no_music") else {}),
            **({"text": _clean_text(i["text"])} if _clean_text(i.get("text")) else {}),
            **({"logo": _clean_logo(i["logo"])} if _clean_logo(i.get("logo")) else {})}


def change(cid, name=None, items=None, text=False, logo=False):
    """Rename it, or put its clips (reordered, trimmed, starred…) as you left them on the page."""
    with _lock:
        c = load(cid)
        if c.get("busy"):
            raise CollectionError("It's being saved: wait a moment.")
        if name is not None:
            c["name"] = name.strip()[:80] or c["name"]
        if items is not None:
            c["items"] = [x for x in (_clean_item(i) for i in items) if x][:500]
        if text is not False:                      # text on every clip (a title, a credit line)
            c["text"] = _clean_text(text)
        if logo is not False:                      # your logo on every clip
            c["logo"] = _clean_logo(logo)
        return _save(c)


def add(cid, jid, clips):
    """Clips from one video, added at the end."""
    with _lock:
        c = load(cid)
        new = [x for x in (_clean_item({**k, "jid": jid}, keep_id=False) for k in clips or []) if x]
        if not new:
            raise CollectionError("No clips to add.")
        c["items"] = (c.get("items") or []) + new
        _save(c)
    return {"added": len(new), **full(cid)}


def remove(cid):
    p = _path(cid)
    if load(cid).get("busy"):
        raise CollectionError("It's being saved: wait a moment.")
    p.unlink(missing_ok=True)


def full(cid):
    """The collection with each clip's video title and size, for the page."""
    c = load(cid)
    titles = {}
    for i in c.get("items") or []:
        if i["jid"] not in titles:
            try:
                j = jobs.load(i["jid"])
                m = j.get("media") or {}
                titles[i["jid"]] = {"title": j.get("title") or "", "duration": m.get("duration") or 0,
                                    "width": m.get("width") or 1920, "height": m.get("height") or 1080}
            except Exception:
                titles[i["jid"]] = {"title": "(this video was deleted)", "duration": 0, "gone": True}
    return {**c, "videos": titles}


# ---------------------------------------------------------------- saving

def export(cid, burn="zh", srt=(), shape=None, name=None):
    c = load(cid)
    if c.get("busy"):
        raise CollectionError("It's already being saved.")
    shape = shape or {}
    items = [i for i in c.get("items") or [] if i.get("star") or not shape.get("starred")]
    items = [i for i in items if i["end"] - i["start"] >= 0.3]
    if not items:
        raise CollectionError("No ★ clips in this collection." if shape.get("starred") else "Add clips first.")
    for i in items:
        jobs.job_dir(i["jid"])
    if burn not in ("zh", "both", "th") and not srt:
        raise CollectionError("Nothing to save: tick an SRT file or choose captions to burn.")
    _update(cid, busy=True, label="Starting", progress=0, error=None)
    threading.Thread(target=_run_export, args=(cid, items, burn, tuple(srt or ()), shape, name), daemon=True).start()
    return load(cid)


def _run_export(cid, items, burn, srt, shape, name):
    try:
        files = _export(cid, items, burn, srt, shape, name)
        _update(cid, busy=False, label="", progress=None, exports=files)
    except Exception as e:
        _update(cid, busy=False, label="", progress=None, error=str(e) or e.__class__.__name__)


def _export(cid, items, burn, srt, shape, name):
    c = load(cid)
    base = jobs._safe((name or "").strip() or c.get("name") or "Collection")
    folder = paths.OUT / "Collections" / jobs._safe(c.get("name") or "Collection")
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    # SRT files: every clip's captions, one after another as in the video
    if srt:
        joined, at = [], 0.0
        for i in items:
            for l in jobs._clip(jobs.lines(i["jid"]), i["start"], i["end"]):
                joined.append({**l, "start": round(l["start"] + at, 3), "end": round(l["end"] + at, 3)})
            at += i["end"] - i["start"]
        for which, suffix in (("th", "th"), ("zh", "zh-TW"), ("both", "zh-TW+th")):
            if which in srt:
                p = jobs._unused(folder / f"{base}.{suffix}.srt")
                p.write_text(captions.srt(joined, which), encoding="utf-8")
                files.append({"kind": f"srt-{which}", "path": str(p)})
    if burn not in ("zh", "both", "th"):
        return files
    work = Path(DIR / f"{cid}-work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    apart = bool(shape.get("apart")) and len(items) > 1
    fade = shape.get("fade", True) and len(items) > 1 and not apart
    total = sum(i["end"] - i["start"] for i in items)
    pieces, done = [], 0.0
    try:
        for n, i in enumerate(items):
            share = (i["end"] - i["start"]) / total
            title = (jobs.load(i["jid"]).get("title") or "")[:40]
            _update(cid, label=f"Clip {n + 1} of {len(items)} ({title})", progress=round(done, 3))
            tag = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", i.get("label") or "").strip()[:40]
            dst = jobs._unused(folder / f"{base} {n + 1:02d}{' ' + tag if tag else ''}.mp4") if apart else work / f"{n:04d}.mp4"
            _piece(i, burn, dst, work / f"{n:04d}", shape, (fade and n > 0, fade and n < len(items) - 1), (c.get("text"), c.get("logo")),
                   lambda p: _update(cid, progress=round(done + share * p * (1 if apart else 0.8), 3)))
            pieces.append(dst)
            done += share * (1 if apart else 0.8)
        if apart:
            return files + [{"kind": "video", "path": str(p)} for p in pieces]
        out = jobs._unused(folder / f"{base}.mp4")
        _update(cid, label="Joining the clips", progress=0.85)
        _join(pieces, out, shape)
        return files + [{"kind": "video", "path": str(out)}]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _piece(i, which, dst, work, shape, fade, every, on_progress):
    """One clip from its own video, with that video's captions and look, plus your text for it (and for every clip)."""
    job = jobs.load(i["jid"])
    d = jobs.job_dir(i["jid"])
    m = job["media"]
    a, b = i["start"], min(i["end"], m.get("duration") or i["end"])
    full = m.get("duration") or 0
    touches = [({**t, "start": 0.0, "end": full} if t.get("whole") else t) for t in jobs.touches(i["jid"]) if not t.get("pending")]
    every_text, every_logo = every
    touches += [_text_touch(t, a, b) for t in (i.get("text"), every_text) if t]
    touches += [_logo_touch(l, a, b) for l in (i.get("logo"), every_logo) if l]
    W, H, st, plan = m.get("width") or 1920, m.get("height") or 1080, job.get("style"), None
    if shape.get("vertical"):
        plan = style.vertical_plan(W, H, shape.get("fit", "fill"), shape.get("pos", 0.5))
        touches = [style.on_vertical(t, plan) for t in touches]
        W, H, st = plan["w"], plan["h"], style.vertical_style(st)
    kept, ls = jobs._clip(touches, a, b), jobs._clip(jobs.lines(i["jid"]), a, b)
    still = [t for t in kept if t.get("motion") not in style.MOTIONS]
    moving = [t for t in kept if t.get("motion") in style.MOTIONS]
    work.mkdir(parents=True, exist_ok=True)
    lst = style.frames(ls, still, which, W, H, st, work, lambda p: on_progress(0.3 * p), job.get("speakers"))
    moves = style.sprites(moving, W, H, st, work, b - a)
    voices = None
    if shape.get("no_music") or i.get("no_music"):
        voices = work / "voices.wav"
        with jobs._gpu:                         # one music remover at a time, shared with the videos
            r = subprocess.run([sys.executable, "-m", "ac.voice", "--keep", str(d / job["source"]), str(voices), f"{a:.3f}", f"{b:.3f}"],
                               cwd=str(paths.ROOT), capture_output=True, text=True)
        if r.returncode != 0 or not voices.exists():
            voices = None                      # the clip keeps its sound rather than failing the save
    apart = bool(shape.get("apart"))
    media.burn(d / job["source"], lst, dst, b - a, lambda p: on_progress(0.3 + 0.7 * p), moves, plan, start=a,
               size=shape.get("size", "full") if apart else "full", canvas=(W, H), fade=fade, audio=voices)


def _join(pieces, out, shape):
    """Clips of different sizes made one: each fitted (scaled, black bars only where needed) to one shape."""
    sizes = [media.probe(p) for p in pieces]
    if shape.get("vertical"):
        W, H = style.VERTICAL
    else:
        W = max(max(s["width"], round(s["height"] * 16 / 9)) for s in sizes)
        W, H = (W + 1) // 2 * 2, (round(W * 9 / 16) + 1) // 2 * 2
    small = media.SIZES.get(shape.get("size"))
    if small:
        W, H = media.out_size(W, H, shape["size"])
    inputs, graph = [], []
    for n, p in enumerate(pieces):
        inputs += ["-i", str(p)]
        graph.append(f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30,format=yuv420p[v{n}]")
        graph.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo[a{n}]")
    graph.append("".join(f"[v{n}][a{n}]" for n in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=1[v][a]")
    quality = ["-b:v", f"{small[1]}k"] if small else ["-q:v", "65"]
    media._run([*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
                "-c:v", "h264_videotoolbox", *quality, "-c:a", "aac", "-b:a", "128k" if small else "192k",
                "-movflags", "+faststart", str(out)], "Joining the clips")
