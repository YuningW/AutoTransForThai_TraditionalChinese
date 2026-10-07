"""Jobs: one per video. Steps run in a background thread and report progress
through job.json, which the page polls.

work/jobs/<id>/
  job.json        state, info, helpers, activity log, exports
  lines.json      the captions (see captions.py)
  source.*        the video
  preview.mp4     what the page plays (a link to source.* when the browser can play it)
  audio.wav       16 kHz mono, what Whisper hears
  voice.wav       the same with music and noise taken away (when asked for)
  helpers/        your screenshots and text files
  relisten/       clips cut for listening again
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import brain, captions, fetch, media, memory, paths

_locks = {}
_gpu = threading.Semaphore(1)        # one Whisper / Demucs run at a time
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".ts", ".flv", ".wmv", ".3gp"}
PICTURE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}
TEXT_EXT = {".srt", ".txt", ".vtt", ".ass"}
RELISTEN_MAX = 40                     # lines the self-check may listen to again per run
UNSURE = 0.55                         # Whisper confidence below this gets a second listen


class JobError(RuntimeError):
    pass


def _lock(jid):
    return _locks.setdefault(jid, threading.RLock())


def job_dir(jid):
    if not re.fullmatch(r"[0-9a-f]{12}", jid or ""):
        raise JobError("Unknown job.")
    d = paths.JOBS / jid
    if not d.exists():
        raise JobError("That job no longer exists.")
    return d


def load(jid):
    job = json.loads((job_dir(jid) / "job.json").read_text())
    job["dir"] = str(paths.JOBS / jid)
    return job


def save(job):
    d = paths.JOBS / job["id"]
    data = {k: v for k, v in job.items() if k != "dir"}
    with _lock(job["id"]):
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(d / "job.json")


def update(jid, **changes):
    with _lock(jid):
        job = load(jid)
        job.update(changes)
        job["updated"] = time.time()
        save(job)
        return job


def log(jid, msg, kind="info"):
    with _lock(jid):
        job = load(jid)
        job.setdefault("activity", []).append({"at": time.time(), "msg": msg, "kind": kind})
        job["activity"] = job["activity"][-60:]
        save(job)


def lines(jid):
    f = job_dir(jid) / "lines.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_lines(jid, ls):
    d = job_dir(jid)
    with _lock(jid):
        tmp = d / "lines.json.tmp"
        tmp.write_text(json.dumps(ls, ensure_ascii=False, indent=0))
        tmp.replace(d / "lines.json")
        job = load(jid)
        job["lines_rev"] = job.get("lines_rev", 0) + 1
        job["counts"] = _counts(ls)
        save(job)


def _counts(ls):
    return {"lines": len(ls), "flagged": sum(1 for l in ls if l.get("flag")),
            "unsure": sum(1 for l in ls if l.get("conf", 1) < UNSURE and l.get("status") == "auto"),
            "fixed": sum(1 for l in ls if l.get("status") == "fixed")}


def locked(l):
    """Lines you typed, or fixed with a note: redo and the self-check leave them alone."""
    return l.get("status") == "edited" or bool(l.get("feedback"))


def listing():
    out = []
    for f in sorted(paths.JOBS.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        out.append({"id": j["id"], "title": j.get("title"), "state": j.get("state"), "busy": j.get("busy"),
                    "updated": j.get("updated"), "duration": (j.get("media") or {}).get("duration"),
                    "counts": j.get("counts")})
    return out


def delete(jid):
    d = job_dir(jid)
    if load(jid).get("busy"):
        raise JobError("Wait for the current step to finish first.")
    shutil.rmtree(d)


def _run(jid, fn, *args):
    def target():
        try:
            fn(jid, *args)
        except Exception as e:  # shown on the page
            msg = str(e) or e.__class__.__name__
            update(jid, busy=False, error=msg, label="", progress=None)
            log(jid, "Stopped: " + msg, "error")
    threading.Thread(target=target, daemon=True).start()


def _begin(jid, state, label=""):
    with _lock(jid):
        job = load(jid)
        if job.get("busy"):
            raise JobError("This video is still busy with the last step.")
        job.update(busy=True, state=state, error=None, progress=None, label=label, updated=time.time())
        save(job)


def _step(jid, state, label, progress=None):
    update(jid, state=state, label=label, progress=progress)


# ---------------------------------------------------------------- new jobs

def _new_job(title, about="", clean_voice=False, fast=False, **fields):
    jid = uuid.uuid4().hex[:12]
    (paths.JOBS / jid / "helpers").mkdir(parents=True)
    job = {"id": jid, "title": title, "about": (about or "").strip(), "created": time.time(), "updated": time.time(),
           "state": "fetching", "busy": True, "label": "Starting", "progress": None, "error": None,
           "options": {"clean_voice": bool(clean_voice), "fast": bool(fast)}, "info": {}, "media": {}, "helpers": [],
           "activity": [], "exports": [], "learned": [], "lines_rev": 0, **fields}
    save(job)
    return load(jid)


def create_from_link(url, about="", clean_voice=False, fast=False):
    url = fetch.clean_url(url)
    key = fetch.video_key(url)
    for f in paths.JOBS.glob("*/job.json"):
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        if j.get("key") == key and j.get("source") and not j.get("error"):
            return load(j["id"])                     # same video again: open the earlier job
    job = _new_job(url, about, clean_voice, fast, key=key, info={"url": url})
    _run(job["id"], _fetch_then_make, url)
    return job


def create_from_upload(filename, stream, about="", clean_voice=False, fast=False):
    ext = Path(filename or "video.mp4").suffix.lower()
    if ext not in VIDEO_EXT:
        raise JobError("That doesn't look like a video file (" + (ext or "no extension") + ").")
    title = Path(filename).stem
    job = _new_job(title, about, clean_voice, fast, info={"title": title, "file": filename})
    dst = job_dir(job["id"]) / ("source" + ext)
    with open(dst, "wb") as f:
        shutil.copyfileobj(stream, f, 4 * 1024 * 1024)
    update(job["id"], source=dst.name)
    _run(job["id"], _make)
    return load(job["id"])


def _fetch_then_make(jid, url):
    _step(jid, "fetching", "Downloading the video", 0)

    def progress(p, label=None):
        update(jid, progress=p, **({"label": label} if label else {}))

    info, path = fetch.download(url, job_dir(jid), progress)
    update(jid, info={**info}, title=info.get("title") or url, source=path.name)
    _make(jid)


# ---------------------------------------------------------------- the main run

def _make(jid):
    """Video in -> Thai heard -> tidied -> translated -> checked and fixed by itself."""
    d = job_dir(jid)
    job = load(jid)
    src = d / job["source"]
    _step(jid, "preparing", "Reading the video")
    info = media.probe(src)
    update(jid, media=info)
    media.browser_copy(src, info, d / "preview.mp4")
    media.extract_audio(src, d / "audio.wav")
    log(jid, f"Video ready: {_mmss(info['duration'])} long.")

    hear = d / "audio.wav"
    if job["options"].get("clean_voice"):
        _isolate_voice(jid)
        hear = d / "voice.wav"

    _step(jid, "listening", "Listening (Whisper)", 0)
    segs = _listen(jid, hear, memory.whisper_hint())
    ls = captions.from_segments(segs)
    if not ls:
        raise JobError("No speech was found in this video.")
    save_lines(jid, ls)
    log(jid, f"Heard {len(ls)} lines; {sum(1 for l in ls if l['conf'] < UNSURE)} of them it wasn't sure about.")

    _read_helpers(jid)
    _polish_and_translate(jid)
    _self_check(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Captions are ready for you to check.", "done")


def _mmss(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def _sub(jid, args, label, weight=(0, 1)):
    """Run a python -m step, pass its progress to the page, return its last message."""
    a, b = weight
    env = dict(os.environ)
    if (load(jid).get("options") or {}).get("fast"):
        env["AC_WHISPER"] = paths.WHISPER_FAST
    p = subprocess.Popen([sys.executable, "-m", *args], cwd=str(paths.ROOT), stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    last = {}
    for line in p.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        last = msg
        if "progress" in msg:
            update(jid, progress=round(a + (b - a) * msg["progress"], 3), label=label)
    p.wait()
    if last.get("error") or p.returncode != 0:
        raise JobError(last.get("error") or f"{label} stopped unexpectedly.")
    return last


def _listen(jid, wav, hint, out_name="segments.json"):
    d = job_dir(jid)
    with _gpu:
        _sub(jid, ["ac.listen", str(wav), str(d / out_name), hint], "Listening (Whisper)")
    return json.loads((d / out_name).read_text())


def _isolate_voice(jid):
    d = job_dir(jid)
    if (d / "voice.wav").exists():
        return
    _step(jid, "cleaning", "Taking the music away from the voices (a few minutes)")
    with _gpu:
        _sub(jid, ["ac.voice", str(d / load(jid)["source"]), str(d / "voice.wav")], "Taking the music away")


# ---------------------------------------------------------------- helpers from you

def add_helper(jid, kind, label, files, text):
    """files: [(filename, bytes)]. kind: "original" (Thai transcript) | "translation"."""
    if kind not in ("original", "translation"):
        raise JobError("Say whether this is the original Thai or a translation.")
    d = job_dir(jid) / "helpers"
    d.mkdir(exist_ok=True)
    hid = uuid.uuid4().hex[:8]
    saved, texts = [], []
    for name, data in files:
        ext = Path(name).suffix.lower()
        if ext in PICTURE_EXT:
            p = d / f"{hid}_{len(saved):02d}{ext}"
            p.write_bytes(data)
            saved.append(p.name)
        elif ext in TEXT_EXT:
            texts.append(data.decode("utf-8-sig", errors="replace"))
        else:
            raise JobError(f"{name}: send pictures (PNG/JPG) or text (.srt/.txt).")
    text = "\n\n".join(t for t in [*texts, (text or "").strip()] if t)
    if not saved and not text:
        raise JobError("Add a picture, a file or some text.")
    h = {"id": hid, "kind": kind, "label": (label or "").strip() or ("CapCut / original captions" if kind == "original" else "Translation"),
         "pictures": saved, "text": text, "items": captions.parse_srt(text) if captions.looks_like_srt(text) else None,
         "read": not saved, "used": False, "added": time.time()}
    with _lock(jid):
        job = load(jid)
        job["helpers"].append(h)
        save(job)
    return h


def remove_helper(jid, hid):
    with _lock(jid):
        job = load(jid)
        for h in job["helpers"]:
            if h["id"] == hid:
                for p in h.get("pictures") or []:
                    (job_dir(jid) / "helpers" / p).unlink(missing_ok=True)
        job["helpers"] = [h for h in job["helpers"] if h["id"] != hid]
        save(job)


def _read_helpers(jid):
    """Screenshots -> text (Claude reads them)."""
    job = load(jid)
    todo = [h for h in job["helpers"] if not h.get("read")]
    for i, h in enumerate(todo):
        _step(jid, "reading", f"Reading your screenshots ({i + 1}/{len(todo)})")
        pics = [job_dir(jid) / "helpers" / p for p in h["pictures"]]
        lang, items = brain.read_pictures(job_dir(jid), pics)
        text = "\n".join((f"{x['start']:.1f}-{x['end']:.1f} " if x.get("start") is not None and x.get("end") is not None else "") + x["text"] for x in items)
        timed = [x for x in items if x.get("start") is not None and x.get("end") is not None]
        with _lock(jid):
            job = load(jid)
            for hh in job["helpers"]:
                if hh["id"] == h["id"]:
                    hh.update(read=True, language=lang, text=(hh.get("text", "") + "\n" + text).strip(),
                              items=timed if len(timed) > len(items) * 0.8 else hh.get("items"))
            save(job)
        log(jid, f"Read {len(items)} lines from “{h['label']}”.")


def _polish_and_translate(jid, keep_edited=True):
    job = load(jid)
    helpers = job["helpers"]
    ls = lines(jid)
    work = [l for l in ls if not (keep_edited and locked(l))]

    _step(jid, "tidying", "Claude is tidying the Thai" + (" using your helpers" if any(h["kind"] == "original" for h in helpers) else ""))
    by_id = {l["id"]: l for l in ls}
    changed = 0
    for r in brain.polish(job, work, helpers):
        l = by_id.get(r["id"])
        if not l:
            continue
        if r["th"].strip() and r["th"].strip() != l["th"]:
            l.setdefault("heard", l["th"])         # what Whisper first wrote, kept for the page
            l["th"] = r["th"].strip()
            changed += 1
        l["kind"] = r["kind"]
        l["suspect"] = bool(r.get("suspect"))
        l["why"] = r.get("reason") or ""
    save_lines(jid, ls)
    log(jid, f"Tidied the Thai: {changed} lines changed.")

    _step(jid, "translating", "Claude is translating into Traditional Chinese")
    for r in brain.translate(job, work, helpers):
        l = by_id[r["id"]]
        l["zh"] = r["zh"].strip()
        if r.get("unsure"):
            l["suspect"] = True
    save_lines(jid, ls)
    with _lock(jid):
        job = load(jid)
        for h in job["helpers"]:
            h["used"] = True
        save(job)
    log(jid, "Translated every line.")


# ---------------------------------------------------------------- self-check

def _self_check(jid):
    """Claude reviews the whole thing; unsure lines get a fresh listen and are fixed without asking you."""
    job = load(jid)
    ls = lines(jid)
    by_id = {l["id"]: l for l in ls}
    _step(jid, "checking", "Checking its own work")
    problems = brain.review(job, [l for l in ls if not locked(l)])

    targets = {}
    for l in ls:
        if l.get("status") == "auto" and l.get("kind") == "speech" and (l["conf"] < UNSURE or l.get("suspect")):
            targets[l["id"]] = {**l, "flag": "heard", "note": l.get("why", ""), "by": "auto"}
    tr_fixed = 0
    for p in problems:
        l = by_id.get(p["id"])
        if not l or locked(l):
            continue
        if p["type"] == "translation" and p.get("fix"):
            if p["id"] in targets:                  # it'll be redone with the fresh listen anyway
                continue
            l.setdefault("zh_before", l["zh"])
            l["zh"], l["status"], l["explain"] = p["fix"].strip(), "fixed", "Self-check: " + p["why"]
            tr_fixed += 1
        elif p["type"] == "heard":
            targets[p["id"]] = {**l, "flag": "heard", "note": p["why"], "by": "auto"}
        elif p["type"] == "timing":
            l["note_auto"] = p["why"]
    save_lines(jid, ls)

    chosen = sorted(targets.values(), key=lambda t: t["conf"])[:RELISTEN_MAX]
    if chosen:
        _fix(jid, chosen, learn=False)
    log(jid, f"Self-check: fixed {tr_fixed} translations and listened again to {len(chosen)} unsure lines.")


# ---------------------------------------------------------------- listening again + fixing

def _relisten(jid, targets):
    """Fresh attempts for each target line: the original sound, and the voice with the music taken away.
    Returns {id: [{"how", "text"}]}."""
    d = job_dir(jid)
    rd = d / "relisten"
    shutil.rmtree(rd, ignore_errors=True)
    rd.mkdir()
    job = load(jid)
    ls = lines(jid)
    idx = {l["id"]: i for i, l in enumerate(ls)}
    hint_base = memory.whisper_hint()
    plan, windows = [], []
    for t in targets:
        a, b = max(0, t["start"] - 0.8), t["end"] + 0.8
        i = idx[t["id"]]
        before = ls[i - 1]["th"] if i > 0 else ""
        hint = (hint_base + " " + before).strip()[-220:]
        orig = rd / f"{t['id']}_orig.wav"
        media.cut_wav(d / "audio.wav", orig, a, b)
        windows.append((t["id"], a, b))
        plan.append({"id": t["id"], "how": "listened again", "wav": str(orig), "hint": hint, "temperature": 0.0})
        plan.append({"id": t["id"], "how": "listened again, less literal", "wav": str(orig), "hint": hint, "temperature": 0.5})

    # Voice only: the windows go through the music remover as one file (much faster than one by one)
    try:
        _step(jid, load(jid)["state"], "Taking the music away from unsure lines")
        joined = _voice_windows(jid, windows)
        for (lid, _a, _b), wav in zip(windows, joined):
            hint = next(p["hint"] for p in plan if p["id"] == lid)
            plan.append({"id": lid, "how": "listened to the voice with the music removed", "wav": str(wav), "hint": hint, "temperature": 0.0})
    except Exception as e:                                       # still fine with the plain attempts
        log(jid, f"Couldn't remove the music for a second listen ({e}).", "warn")

    (rd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
    _step(jid, load(jid)["state"], f"Listening again to {len(targets)} lines", 0)
    with _gpu:
        _sub(jid, ["ac.relisten", str(rd / "plan.json"), str(rd / "out.json")], f"Listening again to {len(targets)} lines")
    results = json.loads((rd / "out.json").read_text())
    out = {}
    for p, text in zip(plan, results):
        if text:
            out.setdefault(p["id"], []).append({"how": p["how"], "text": text})
    return out


def _voice_windows(jid, windows):
    """Cut every window from the video's sound, join them with silence, take the music out once, cut back apart."""
    import wave
    d = job_dir(jid)
    rd = d / "relisten"
    if (d / "voice.wav").exists():
        outs = []
        for lid, a, b in windows:
            p = rd / f"{lid}_voice.wav"
            media.cut_wav(d / "voice.wav", p, a, b)
            outs.append(p)
        return outs
    gap = 1.0
    sr = 16000
    pieces = []
    for lid, a, b in windows:
        p = rd / f"{lid}_orig.wav"
        with wave.open(str(p)) as w:
            pieces.append(w.readframes(w.getnframes()))
    silence = b"\x00\x00" * int(sr * gap)
    joined = rd / "joined.wav"
    with wave.open(str(joined), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for p in pieces:
            w.writeframes(p + silence)
    with _gpu:
        _sub(jid, ["ac.voice", str(joined), str(rd / "joined_voice.wav")], "Taking the music away")
    outs, pos = [], 0.0
    for (lid, a, b), raw in zip(windows, pieces):
        dur = len(raw) / 2 / sr
        p = rd / f"{lid}_voice.wav"
        media.cut_wav(rd / "joined_voice.wav", p, pos, pos + dur)
        outs.append(p)
        pos += dur + gap
    return outs


def _fix(jid, targets, learn=True):
    """Fix the target lines: listen again where the words may be wrong, then ask Claude."""
    job = load(jid)
    need_ears = [t for t in targets if t.get("flag") in ("heard", "other")]
    relistened = _relisten(jid, need_ears) if need_ears else {}
    _step(jid, load(jid)["state"], f"Claude is fixing {len(targets)} lines")
    ls = lines(jid)
    by_id = {l["id"]: l for l in ls}
    result = {"lines": [], "lessons": []}
    for i in range(0, len(targets), 25):
        r = brain.fix(job, ls, targets[i:i + 25], relistened)
        result["lines"] += r["lines"]
        result["lessons"] += r["lessons"]
    changed, neighbours = 0, 0
    target_ids = {t["id"] for t in targets}
    for r in result["lines"]:
        l = by_id.get(r["id"])
        if not l:
            continue
        t = next((x for x in targets if x["id"] == r["id"]), None)
        if t is None:                          # a neighbour it also fixed; never one you typed yourself
            if locked(l):
                continue
            t = {"id": r["id"], "by": "auto"}
        new_th, new_zh = r["th"].strip(), r["zh"].strip()
        if new_th != l["th"] or new_zh != l.get("zh"):
            if r["id"] in target_ids:
                changed += 1
            else:
                neighbours += 1
            l.setdefault("th_before", l["th"])
            l.setdefault("zh_before", l.get("zh", ""))
            if t.get("by") == "user":
                memory.remember_example(new_th, l.get("zh", ""), new_zh, th_before=l["th"], note=t.get("note", ""))
            l["th"], l["zh"] = new_th, new_zh
            l["status"] = "fixed"
        l["explain"] = r.get("explain", "")
        l["attempts"] = relistened.get(r["id"], [])
        l["suspect"] = False
        if t.get("by") == "user":
            l["flag"], l["note"] = None, ""
            l["feedback"] = t.get("note", "")
    save_lines(jid, ls)
    added = memory.learn(result["lessons"], source=load(jid).get("title", "")) if learn else []
    if added:
        with _lock(jid):
            job = load(jid)
            job["learned"] = (job.get("learned") or []) + added
            save(job)
        log(jid, "Learned for next time: " + "; ".join(a.get("rule") or f"{a.get('th')} → {a.get('zh')}" for a in added), "learn")
    return changed, neighbours


def fix_flagged(jid):
    ls = lines(jid)
    flagged = [{**l, "by": "user"} for l in ls if l.get("flag")]
    if not flagged:
        raise JobError("Flag at least one line first (the ⚑ button on a line).")
    _begin(jid, "fixing", f"Fixing {len(flagged)} lines")
    _run(jid, _fix_job, flagged)


def _fix_job(jid, flagged):
    n, extra = _fix(jid, flagged, learn=True)
    update(jid, busy=False, state="ready", label="", progress=None)
    msg = f"Changed {n} of the {len(flagged)} lines you flagged"
    if n < len(flagged):
        msg += " (the rest looked right after listening again; see the note on each line)"
    if extra:
        msg += f", plus {extra} line{'s' if extra > 1 else ''} next to them"
    log(jid, msg + ".", "done")


def edit_line(jid, lid, changes):
    """Your own edits and flags. Typed text is kept as-is and remembered as an example."""
    with _lock(jid):
        ls = lines(jid)
        l = next((x for x in ls if x["id"] == lid), None)
        if not l:
            raise JobError("That line is gone.")
        if "flag" in changes:
            l["flag"] = changes["flag"] or None
        if "note" in changes:
            l["note"] = (changes["note"] or "").strip()
        for k in ("th", "zh"):
            if k in changes and changes[k] is not None and changes[k].strip() != l.get(k, ""):
                if k == "zh":
                    memory.remember_example(l["th"], l.get("zh", ""), changes[k].strip(), note="typed by the user")
                l.setdefault(k + "_before", l.get(k, ""))
                l[k] = changes[k].strip()
                l["status"] = "edited"
        for k in ("start", "end"):
            if k in changes and changes[k] is not None:
                l[k] = round(max(0.0, float(changes[k])), 3)
        if l["end"] <= l["start"]:
            l["end"] = round(l["start"] + 0.5, 3)
        save_lines(jid, ls)
        return l


def redo(jid, what):
    """Run Claude again over the whole video, e.g. after adding helpers or after it has learned more."""
    if what not in ("all", "translation"):
        raise JobError("Unknown redo.")
    _begin(jid, "redoing", "Starting again with what it knows now")
    _run(jid, _redo_job, what)


def _redo_job(jid, what):
    _read_helpers(jid)
    if what == "all":
        _polish_and_translate(jid)
    else:
        job = load(jid)
        ls = lines(jid)
        by_id = {l["id"]: l for l in ls}
        _step(jid, "translating", "Claude is translating again with what it has learned")
        for r in brain.translate(job, [l for l in ls if not locked(l)], job["helpers"]):
            by_id[r["id"]]["zh"] = r["zh"].strip()
        save_lines(jid, ls)
    _self_check(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Redone with your helpers and everything it has learned.", "done")


def retry(jid):
    """Pick up after an error."""
    job = load(jid)
    if job.get("busy"):
        raise JobError("Still working.")
    if not job.get("source"):
        if not (job.get("info") or {}).get("url"):
            raise JobError("Nothing to retry; start again with the video.")
        _begin(jid, "fetching", "Downloading the video")
        _run(jid, _fetch_then_make, job["info"]["url"])
    elif not lines(jid):
        _begin(jid, "preparing", "Reading the video")
        _run(jid, _make)
    else:
        redo(jid, "all")


# ---------------------------------------------------------------- export

def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", name or "captions").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > 80:                       # cut at a space, not in the middle of a word
        cut = name[:80]
        name = cut[:cut.rfind(" ")] if cut.rfind(" ") > 40 else cut
    return name.strip(" .-|,") or "captions"


def export(jid, srt=True, burn="zh", style=None):
    job = load(jid)
    if job.get("busy"):
        raise JobError("Wait for the current step to finish first.")
    ls = lines(jid)
    if not ls:
        raise JobError("There are no captions yet.")
    folder = paths.OUT / _safe(job.get("title"))
    folder.mkdir(parents=True, exist_ok=True)
    base = _safe(job.get("title"))
    files = []
    if srt:
        for which, suffix in (("th", "th"), ("zh", "zh-TW"), ("both", "zh-TW+th")):
            p = folder / f"{base}.{suffix}.srt"
            p.write_text(captions.srt(ls, which), encoding="utf-8")
            files.append({"kind": f"srt-{which}", "path": str(p)})
    update(jid, exports=files, export_folder=str(folder))
    if burn in ("zh", "both", "th"):
        _begin(jid, "burning", "Burning captions into the video", )
        _run(jid, _burn_job, burn, style or {}, folder, base, files)
    return load(jid)


def _burn_job(jid, which, style, folder, base, files):
    job = load(jid)
    d = job_dir(jid)
    m = job["media"]
    ass_file = d / "burn.ass"
    ass_file.write_text(captions.ass(lines(jid), which, m.get("width"), m.get("height"), style), encoding="utf-8")
    label = {"zh": "中文字幕", "both": "中泰字幕", "th": "Thai captions"}[which]
    out = folder / f"{base} ({label}).mp4"
    media.burn(d / job["source"], ass_file, out, m.get("duration"), lambda p: update(jid, progress=round(p, 3)))
    files = files + [{"kind": f"video-{which}", "path": str(out)}]
    update(jid, busy=False, state="ready", label="", progress=None, exports=files)
    log(jid, f"Saved the captioned video to {str(out).replace(str(Path.home()), '~')}.", "done")
