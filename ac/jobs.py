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
import contextlib
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

from . import brain, captions, fetch, media, memory, models, paths, procs, style, voices, vsubs

_locks = {}
_gpu = threading.Semaphore(1)        # one Whisper / Demucs run at a time
_gpu_holder = {}                      # the video whose turn it is
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".ts", ".flv", ".wmv", ".3gp"}
PICTURE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}
TEXT_EXT = {".srt", ".txt", ".vtt", ".ass"}
THIN_LETTERS_PER_SECOND = 4.0         # captions this sparse over talking: words were lost
RELISTEN_MAX = 40                     # lines the self-check may listen to again per run
SUBS_FILL_MAX = 20                    # stretches a run fills in where the video's subtitles show talking
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
        procs.current.jid = jid
        procs.clear(jid)
        try:
            fn(jid, *args)
        except Exception as e:  # shown on the page
            if procs.stopped(jid) or isinstance(e, procs.Stopped):
                _after_stop(jid)
            else:
                msg = str(e) or e.__class__.__name__
                update(jid, busy=False, error=msg, label="", progress=None)
                log(jid, "Stopped: " + msg, "error")
        finally:
            procs.clear(jid)
    threading.Thread(target=target, daemon=True).start()


def stop(jid):
    """The Stop button: end whatever this video is doing. What's already done is kept."""
    job = load(jid)
    if not job.get("busy"):
        return job
    procs.stop(jid)
    update(jid, label="Stopping…")
    return load(jid)


def _after_stop(jid):
    has_lines = bool(lines(jid))
    what = load(jid).get("state")
    update(jid, busy=False, label="", progress=None, state="ready" if has_lines else "stopped",
           error=None if has_lines else "You stopped it before the captions were made. Press Try again to start over.")
    log(jid, "You stopped it" + (f" while {STATE_DOING.get(what, 'working')}" if what else "") +
        (". Everything finished before that is kept." if has_lines else "."), "warn")


STATE_DOING = {"timing": "lining up the timing", "filling": "filling in skipped talking", "fetching": "downloading", "preparing": "reading the video", "cleaning": "removing the music",
               "listening": "listening", "reading": "reading your screenshots", "tidying": "tidying the Thai",
               "translating": "translating", "checking": "checking its work", "fixing": "fixing your flags",
               "reviewing": "fixing a stretch", "burning": "saving the video", "touches": "picking emoji",
               "speakers": "working out who's talking", "redoing": "redoing"}


def _begin(jid, state, label=""):
    with _lock(jid):
        job = load(jid)
        if job.get("busy"):
            raise JobError("This video is still busy with the last step.")
        job.update(busy=True, state=state, error=None, progress=None, label=label, updated=time.time())
        save(job)


def _step(jid, state, label, progress=None):
    procs.check(jid)
    update(jid, state=state, label=label, progress=progress)


# ---------------------------------------------------------------- new jobs

def _new_job(title, about="", clean_voice=False, fast=False, video_subs=True, subs_check=False, careful=False, **fields):
    subs_check = bool(subs_check and video_subs)
    paths.save_settings({"clean_voice": bool(clean_voice), "fast": bool(fast), "video_subs": bool(video_subs),
                         "subs_check": subs_check, "careful": bool(careful)})
    jid = uuid.uuid4().hex[:12]
    (paths.JOBS / jid / "helpers").mkdir(parents=True)
    job = {"id": jid, "title": title, "about": (about or "").strip(), "created": time.time(), "updated": time.time(),
           "state": "fetching", "busy": True, "label": "Starting", "progress": None, "error": None,
           "options": {"clean_voice": bool(clean_voice), "fast": bool(fast), "video_subs": bool(video_subs), "subs_check": subs_check,
                       "careful": bool(careful), "listen_model": models.listen_key(),
                       "claude_model": models.claude_model()},
           "style": paths.load_settings().get("style") or {},
           "speakers": [dict(p) for p in memory.load().get("people") or []], "info": {}, "media": {}, "helpers": [],
           "activity": [], "exports": [], "learned": [], "lines_rev": 0, **fields}
    save(job)
    return load(jid)


def create_from_link(url, about="", clean_voice=False, fast=False, video_subs=True, subs_check=False, careful=False):
    url = fetch.clean_url(url)
    key = fetch.video_key(url)
    for f in paths.JOBS.glob("*/job.json"):
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        if j.get("key") == key and j.get("source") and not j.get("error"):
            return load(j["id"])                     # same video again: open the earlier job
    job = _new_job(url, about, clean_voice, fast, video_subs, subs_check, careful, key=key, info={"url": url})
    _run(job["id"], _fetch_then_make, url)
    return job


def create_from_upload(filename, stream, about="", clean_voice=False, fast=False, video_subs=True, subs_check=False, careful=False):
    ext = Path(filename or "video.mp4").suffix.lower()
    if ext not in VIDEO_EXT:
        raise JobError("That doesn't look like a video file (" + (ext or "no extension") + ").")
    title = Path(filename).stem
    job = _new_job(title, about, clean_voice, fast, video_subs, subs_check, careful, info={"title": title, "file": filename})
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

    reader = None
    if job["options"].get("video_subs", True):
        reader = threading.Thread(target=_video_subs_quietly, args=(jid,), daemon=True)
        reader.start()

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

    if reader:
        _step(jid, "reading", "Finishing reading the video's own subtitles")
        reader.join()
    _read_helpers(jid)
    _polish_and_translate(jid)
    _finish(jid)


def _finish(jid):
    if load(jid)["options"].get("careful"):
        _careful(jid)
    _self_check(jid)
    _fill_from_subtitles(jid)
    _retime(jid)
    _auto_voices(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Captions are ready for you to check." + _usage_note(jid), "done")


def _usage_note(jid):
    t = brain.usage(job_dir(jid))["total"]
    if not t["calls"]:
        return ""
    read = t["input"] + t["cache_write"] + t["cache_read"]
    return f" Claude read {read / 1000:,.0f}k tokens and wrote {t['output'] / 1000:,.0f}k so far for this video ({t['calls']} requests)."


def _resume(jid, state):
    """Carry on from the step that stopped (Claude's usage limit, a lost connection…), keeping what was done."""
    if state in ("reading", "tidying"):
        _read_helpers(jid)
        _polish_and_translate(jid)
    elif state == "translating":
        _translate(jid)
    _finish(jid)


def _auto_voices(jid):
    """Your usual people's voices are remembered: colour the lines they clearly say. Never stops the run."""
    names = {p.get("name") for p in load(jid).get("speakers") or []}
    ids = {"id:" + p["id"] for p in load(jid).get("speakers") or []}
    if any((n in names or n in ids) and v[1] >= 3 for n, v in memory.remembered_voices().items()):
        try:
            _step(jid, "speakers", "Recognising voices you've taught it")
            _recognise(jid)
        except Exception as e:
            log(jid, f"Couldn't recognise voices ({e}).", "warn")


def _mmss(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


@contextlib.contextmanager
def _gpu_turn(jid):
    """Listening, music removal and alignment run one video at a time (together they'd be slower and could run out
    of memory). While another video has its turn, this one says so instead of sitting at 0%, and Stop still works."""
    if not _gpu.acquire(blocking=False):
        other = _gpu_holder.get("jid")
        title = (load(other).get("title") or "another video") if other else "another video"
        was = load(jid).get("label")
        update(jid, label=f"Waiting for “{title[:50]}” to finish listening (one video at a time)", progress=None)
        while not _gpu.acquire(timeout=1):
            procs.check(jid)
        update(jid, label=was)                     # its turn: back to what it's doing
    _gpu_holder["jid"] = jid
    try:
        yield
    finally:
        _gpu_holder.pop("jid", None)
        _gpu.release()


def _sub(jid, args, label, weight=(0, 1)):
    """Run a python -m step, pass its progress to the page, return its last message."""
    a, b = weight
    split = models.split_at_pauses(_listen_key(jid))
    env = {**os.environ, "AC_WHISPER": _whisper(jid), "AC_SPLIT_AT_PAUSES": "1" if split else "0",
           # Thai-tuned models' word timings are all zero gaps (useless) and cost a third of the time
           "AC_WORD_TIMES": "0" if split else "1"}
    procs.check(jid)
    p = subprocess.Popen([sys.executable, "-m", *args], cwd=str(paths.ROOT), stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    procs.register(p)
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
    procs.unregister(p)
    procs.check(jid)
    if last.get("error") or p.returncode != 0:
        raise JobError(last.get("error") or f"{label} stopped unexpectedly.")
    return last


def _listen_key(jid):
    opts = load(jid).get("options") or {}
    return models.QUICK if opts.get("fast") else (opts.get("listen_model") or models.listen_key())


def _whisper(jid):
    """The listening model for this video, made ready (Thai-tuned ones are converted once)."""
    key = _listen_key(jid)
    if not models.is_ready(key) and "hf" in models.LISTEN.get(key, {}):
        update(jid, label=f"Getting {models.LISTEN[key]['label']} ready (one time, a few minutes)", progress=None)
    return models.mlx_path(key)


def _listen(jid, wav, hint, out_name="segments.json"):
    d = job_dir(jid)
    with _gpu_turn(jid):
        _sub(jid, ["ac.listen", str(wav), str(d / out_name), hint], "Listening (Whisper)")
    return json.loads((d / out_name).read_text())


def _isolate_voice(jid):
    d = job_dir(jid)
    if (d / "voice.wav").exists():
        return
    _step(jid, "cleaning", "Taking the music away from the voices (a few minutes)")
    with _gpu_turn(jid):
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


def _add_found_helper(jid, h):
    """A helper the tool found itself (the video's own captions or burned-in subtitles)."""
    with _lock(jid):
        job = load(jid)
        if any(x.get("label") == h["label"] for x in job["helpers"]):
            return False                                     # found before
        job["helpers"].append({"id": uuid.uuid4().hex[:8], "pictures": [], "read": True, "used": False,
                               "added": time.time(), "found": True, **h})
        save(job)
    return True


def _video_subs(jid, on_progress=None):
    """Caption tracks + subtitles burned into the picture -> helpers. Returns what it found."""
    d = job_dir(jid)
    job = load(jid)
    found = []
    tracks = {k: captions.parse_srt(f.read_text(encoding="utf-8", errors="replace"))
              for k, f in fetch.caption_files(d).items()}
    tracks.update({k: v for k, v in vsubs.tracks_in_file(d / job["source"], d).items() if k not in tracks})
    for lang, cues in tracks.items():
        if cues and _add_found_helper(jid, vsubs.helper_for(lang, cues, "The video's own captions")):
            found.append(f"{vsubs.LABELS[lang]} captions ({len(cues)} lines)")
    burned = vsubs.read_picture(d / job["source"], (job.get("media") or {}).get("duration"), on_progress)
    for lang, cues in burned.items():
        if _add_found_helper(jid, vsubs.helper_for(lang, cues, "Subtitles in the picture")):
            found.append(f"{vsubs.LABELS[lang]} subtitles in the picture ({len(cues)} lines)")
    return found


def _video_subs_quietly(jid):
    """While it listens: never stops the run, says what it found."""
    try:
        procs.current.jid = jid
        found = _video_subs(jid)
        log(jid, "Found subtitles the video already has, used as help: " + "; ".join(found) + "." if found
            else "The video has no subtitles of its own to use as help.")
    except Exception as e:
        log(jid, f"Couldn't read the video's own subtitles ({e}).", "warn")


def find_video_subs(jid):
    _begin(jid, "reading", "Reading the subtitles in the video")
    _run(jid, _find_subs_job)


def _find_subs_job(jid):
    found = _video_subs(jid, lambda p: update(jid, progress=round(p, 3)))
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, ("Found: " + "; ".join(found) + ". Press “Redo the captions with this help” to use it.") if found
        else "This video has no subtitles of its own (no caption tracks, and nothing readable in the picture).", "done")


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
        parts = [x.strip() for x in r.get("parts") or [] if x.strip()]
        if len(parts) > 1:
            l["_parts"] = parts
    ls, n_split = _split_parts(ls)
    by_id = {l["id"]: l for l in ls}
    work = [l for l in ls if not (keep_edited and locked(l))]
    save_lines(jid, ls)
    if n_split:
        log(jid, f"Cut {n_split} long lines where the speaker or sentence changes.")
    log(jid, f"Tidied the Thai: {changed} lines changed.")
    _translate(jid, keep_edited)


def _translate(jid, keep_edited=True):
    job = load(jid)
    ls = lines(jid)
    by_id = {l["id"]: l for l in ls}
    work = [l for l in ls if not (keep_edited and locked(l))]
    _step(jid, "translating", "Claude is translating into Traditional Chinese")
    for r in brain.translate(job, work, job["helpers"]):
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


def _split_parts(ls):
    """Lines Claude cut into parts (one speaker or sentence each): each cut lands on the nearest pause."""
    out, n, next_id = [], 0, max((l["id"] for l in ls), default=0) + 1
    for l in ls:
        parts = l.pop("_parts", None)
        if not parts:
            out.append(l)
            continue
        n += 1
        for i, (p, (a, b)) in enumerate(zip(parts, captions.cut_times(l["start"], l["end"], parts, l.get("gaps")))):
            piece = {**l, "th": p, "start": round(a, 3), "end": round(b, 3),
                     "gaps": [g for g in l.get("gaps") or [] if a < g < b]}
            if i:
                piece["id"] = next_id
                next_id += 1
            out.append(piece)
    return out, n


# ---------------------------------------------------------------- self-check

def _self_check(jid):
    """Claude reviews the whole thing; unsure lines get a fresh listen and are fixed without asking you."""
    job = load(jid)
    ls = lines(jid)
    by_id = {l["id"]: l for l in ls}
    _step(jid, "checking", "Checking its own work")
    problems = brain.review(job, [l for l in ls if not locked(l)], _check_refs(job))

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
    hint_base = ""            # no learned-word hint on short clips: over music Whisper just repeats it
    best = models.mlx_path(models.listen_key())          # short clips: the best model, even on Quicker listening
    plan, windows = [], []
    for t in targets:
        a, b = max(0, t["start"] - 0.8), t["end"] + 0.8
        i = idx[t["id"]]
        before = ls[i - 1]["th"] if i > 0 else ""
        hint = (hint_base + " " + before).strip()[-220:]
        orig = rd / f"{t['id']}_orig.wav"
        media.cut_wav(d / "audio.wav", orig, a, b)
        windows.append((t["id"], a, b))
        plan.append({"id": t["id"], "how": "listened again", "wav": str(orig), "hint": hint, "temperature": 0.0, "model": best})

    # Voice only: the windows go through the music remover as one file (much faster than one by one)
    try:
        _step(jid, load(jid)["state"], "Taking the music away from unsure lines")
        joined = _voice_windows(jid, windows)
        for (lid, _a, _b), wav in zip(windows, joined):
            hint = next(p["hint"] for p in plan if p["id"] == lid)
            plan.append({"id": lid, "how": "listened to the voice with the music removed", "wav": str(wav), "hint": hint, "temperature": 0.0, "model": best})
    except Exception as e:                                       # still fine with the plain attempts
        log(jid, f"Couldn't remove the music for a second listen ({e}).", "warn")

    (rd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
    _step(jid, load(jid)["state"], f"Listening again to {len(targets)} lines", 0)
    with _gpu_turn(jid):
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
    with _gpu_turn(jid):
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
        r = brain.fix(job, ls, targets[i:i + 25], relistened, _check_refs(job))
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


def _with_claude(model, effort):
    """For this run only: the Claude model and effort you picked for it (else the ones under Models). Says which."""
    models.use(model, effort)
    m = models.CLAUDE.get(models.claude_model(), {}).get("label", models.claude_model())
    e = models.claude_effort("high")
    return f"{m}, effort {models.EFFORTS.get(e, {}).get('label', e or 'n/a')}"


def fix_flagged(jid, model=None, effort=None):
    ls = lines(jid)
    flagged = [{**l, "by": "user"} for l in ls if l.get("flag")]
    if not flagged:
        raise JobError("Flag at least one line first (the ⚑ button on a line).")
    _begin(jid, "fixing", f"Fixing {len(flagged)} lines")
    _run(jid, _fix_job, flagged, model, effort)


def _fix_job(jid, flagged, model=None, effort=None):
    log(jid, f"Fixing {len(flagged)} flagged lines with {_with_claude(model, effort)}.")
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
                l["timed"] = "you"                  # lining up the timing later leaves it alone
        if "speaker" in changes:
            l["speaker"] = changes["speaker"] or None
            l.pop("speaker_guess", None)
        if "paint" in changes:                # some words in their own colour
            paint = []
            for m in changes["paint"] or []:
                if isinstance(m, dict) and m.get("f") in ("zh", "th") and isinstance(m.get("text"), str) and m["text"].strip() \
                        and isinstance(m.get("color"), str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", m["color"]):
                    paint.append({"f": m["f"], "text": m["text"][:200], "n": max(0, int(m.get("n") or 0)), "color": m["color"]})
            if paint:
                l["paint"] = paint[:30]
            else:
                l.pop("paint", None)
        if "look" in changes:                 # this line's own size, colour, position…; {} = like all the others
            look = style.clean_look(changes["look"])
            if look:
                l["look"] = look
            else:
                l.pop("look", None)
        if l["end"] <= l["start"]:
            l["end"] = round(l["start"] + 0.5, 3)
        if "start" in changes:
            ls.sort(key=lambda x: (x["start"], x["end"]))      # moved on the timeline: keep the order by time
        save_lines(jid, ls)
        return l


WAVE_RATE = 50                       # waveform points per second, for the timeline


def waveform(jid):
    """The sound's loudness, WAVE_RATE points a second, 0-255 each: the timeline draws it under the captions."""
    d = job_dir(jid)
    wav, out = d / "audio.wav", d / "waveform.bin"
    if not wav.exists():
        raise JobError("This video has no sound yet.")
    if out.exists() and out.stat().st_mtime >= wav.stat().st_mtime:
        return out.read_bytes()
    import numpy as np
    from . import listen
    x = np.abs(listen.load_wav(wav))
    step = listen.SR // WAVE_RATE
    n = len(x) // step
    peaks = x[:n * step].reshape(n, step).max(axis=1)
    top = float(np.percentile(peaks, 99.5)) or 1.0
    data = (np.sqrt(np.clip(peaks / top, 0, 1)) * 255).astype(np.uint8).tobytes()
    out.write_bytes(data)
    return data


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
    _fill_from_subtitles(jid)
    _retime(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Redone with your helpers and everything it has learned.", "done")


def listen_again(jid, clean_voice=True):
    """Start the listening over (e.g. with the music removed). Lines you typed or fixed with a note stay."""
    job = load(jid)
    if not job.get("source"):
        raise JobError("The video isn't here yet.")
    with _lock(jid):
        job = load(jid)
        job["options"] = {**job["options"], "clean_voice": bool(clean_voice), "listen_model": models.listen_key(),
                          "claude_model": models.claude_model()}
        save(job)
    _begin(jid, "listening", "Starting over")
    _run(jid, _listen_again_job)


def _listen_again_job(jid):
    d = job_dir(jid)
    hear = d / "audio.wav"
    if load(jid)["options"].get("clean_voice"):
        _isolate_voice(jid)
        hear = d / "voice.wav"
    _step(jid, "listening", "Listening (Whisper)", 0)
    segs = _listen(jid, hear, memory.whisper_hint())
    old = lines(jid)
    keep = [l for l in old if locked(l)]
    first = max((l["id"] for l in old), default=0) + 1
    fresh = [l for l in captions.from_segments(segs, first_id=first)
             if not any(l["start"] < k["end"] and l["end"] > k["start"] for k in keep)]
    save_lines(jid, captions.fix_timing(keep + fresh))
    log(jid, f"Listened again{' with the music removed' if load(jid)['options'].get('clean_voice') else ''}: "
             f"{len(fresh)} lines, plus {len(keep)} of yours kept.")
    _read_helpers(jid)
    _polish_and_translate(jid)
    _self_check(jid)
    _fill_from_subtitles(jid)
    _retime(jid)
    _auto_voices(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Captions are ready for you to check.", "done")


def recover_interrupted():
    """At start-up: a job still marked busy was cut off when AutoCaption stopped. Free it."""
    for f in paths.JOBS.glob("*/job.json"):
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        if not j.get("busy"):
            continue
        has_lines = (f.parent / "lines.json").exists()
        what = {"reviewing": "Fix a stretch", "fixing": "Fix flagged lines", "burning": "Save",
                "touches": "Let Claude suggest some"}.get(j.get("state"), "")
        if has_lines and what:
            msg = f"“{what}” was cut off when AutoCaption stopped. Nothing was lost; run it again."
            update(j["id"], busy=False, state="ready", label="", progress=None, error=None)
            log(j["id"], msg, "warn")
        else:
            update(j["id"], busy=False, label="", progress=None,
                   error="AutoCaption stopped while working on this. Press Try again.")


RESUMABLE = ("reading", "tidying", "translating", "checking")


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
    elif job.get("state") in RESUMABLE:      # stopped part-way through making the captions: carry on from there
        state = job["state"]
        _begin(jid, state, "Carrying on")
        log(jid, f"Carrying on from {STATE_DOING.get(state, state)}.")
        _run(jid, _resume, state)
    else:                                   # captions are there: just clear the message
        update(jid, error=None, state="ready")


# ---------------------------------------------------------------- export

def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", name or "captions").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > 80:                       # cut at a space, not in the middle of a word
        cut = name[:80]
        name = cut[:cut.rfind(" ")] if cut.rfind(" ") > 40 else cut
    return name.strip(" .-|,") or "captions"


def _clip(items, a, b):
    """Lines or touches in the part a..b, cut to it and moved so the part starts at 0."""
    out = []
    for x in items:
        s, e = max(x["start"], a), min(x["end"], b)
        if e - s >= 0.1:
            out.append({**x, "start": round(s - a, 3), "end": round(e - a, 3)})
    return out


PEOPLE_PAD = (0.3, 0.5)      # a person's part starts a little before their line and ends a little after
PEOPLE_JOIN = 1.5            # their parts closer than this are kept as one (no jump cut)


def _spans(job, ls, part):
    """The stretches to save: None for the whole video, else [(start, end)]. part: {"start", "end"} for one
    part, or {"people": [ids]} for every stretch where those people talk (joined into one video)."""
    if not part:
        return None
    dur = (job.get("media") or {}).get("duration") or 1e9
    if part.get("reel"):                      # your clips (the Clips tab), in the order you put them
        spans = [(max(0.0, float(c["start"])), min(dur, float(c["end"]))) for c in job.get("reel") or []]
        spans = [(round(a, 3), round(b, 3)) for a, b in spans if b - a >= 0.3]
        if not spans:
            raise JobError("Add clips first (the Clips tab: I to start a clip, O to end it).")
        return spans
    if part.get("spans"):                     # the list of parts as you left it on the page (some dropped or nudged)
        spans = []
        for a, b in sorted((max(0.0, float(a)), min(dur, float(b))) for a, b in part["spans"]):
            if b - a < 0.3:
                continue
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        if not spans:
            raise JobError("Every part was left out: keep at least one.")
        return [(round(a, 3), round(b, 3)) for a, b in spans]
    if part.get("people"):
        who = set(part["people"])
        mine = sorted((l for l in ls if l.get("speaker") in who and l.get("kind") != "sound"), key=lambda l: l["start"])
        if not mine:
            raise JobError("None of the lines are marked as said by them yet. Pick who says each line first (the chip on a line, or tick lines and assign).")
        spans = []
        for l in mine:
            a, b = max(0.0, l["start"] - PEOPLE_PAD[0]), min(dur, l["end"] + PEOPLE_PAD[1])
            if spans and a - spans[-1][1] < PEOPLE_JOIN:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        return [(round(a, 3), round(b, 3)) for a, b in spans]
    a, b = max(0.0, float(part.get("start", 0))), min(dur, float(part.get("end", 0)))
    if b - a < 0.5:
        raise JobError("Choose a part at least half a second long (From here / To here).")
    return [(round(a, 3), round(b, 3))]


def set_reel(jid, clips):
    """Your clips (the Clips tab): [{"id", "start", "end", "label"}], in the order you want them."""
    dur = (load(jid).get("media") or {}).get("duration") or 1e9
    clean = []
    for c in clips or []:
        try:
            a, b = max(0.0, float(c["start"])), min(dur, float(c["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if b - a >= 0.1:
            clean.append({"id": str(c.get("id") or uuid.uuid4().hex[:6])[:12], "start": round(a, 3), "end": round(b, 3),
                          "label": str(c.get("label") or "")[:60]})
    with _lock(jid):
        job = load(jid)
        job["reel"] = clean[:200]
        save(job)
    return clean


def _joined(items, spans):
    """Lines or touches in the stretches, each stretch moved to follow the one before (as in the saved video)."""
    out, at = [], 0.0
    for a, b in spans:
        out += [{**x, "start": round(x["start"] + at, 3), "end": round(x["end"] + at, 3)} for x in _clip(items, a, b)]
        at += b - a
    return out


def export(jid, srt=True, burn="zh", shape=None, part=None):
    job = load(jid)
    if job.get("busy"):
        raise JobError("Wait for the current step to finish first.")
    ls = lines(jid)
    if not ls:
        raise JobError("There are no captions yet.")
    spans = _spans(job, ls, part)
    folder = paths.OUT / _safe(job.get("title"))
    folder.mkdir(parents=True, exist_ok=True)
    base = _safe(job.get("title"))
    if spans:                                 # just part of it: its own files, timed from the start of what's saved
        ls = _joined(ls, spans)
        if not ls:
            raise JobError("There are no captions in that part.")
        if part.get("reel"):
            base = f"{base} (clips)"
        elif part.get("people"):
            names = [p.get("name") or "?" for p in job.get("speakers") or [] if p["id"] in part["people"]]
            base = f"{base} ({' + '.join(names)} only)"
        else:
            base = f"{base} {_mmss(spans[0][0]).replace(':', '.')}-{_mmss(spans[0][1]).replace(':', '.')}"
    files = []
    wanted = ("th", "zh", "both") if srt is True else tuple(srt or ())     # which SRT files (none is fine)
    for which, suffix in (("th", "th"), ("zh", "zh-TW"), ("both", "zh-TW+th")):
        if which in wanted:
            p = folder / f"{base}.{suffix}.srt"
            p.write_text(captions.srt(ls, which), encoding="utf-8")
            files.append({"kind": f"srt-{which}", "path": str(p)})
    remember = None if not spans else {"reel": True} if part.get("reel") else \
        {"people": part["people"], "spans": [list(s) for s in spans]} if part.get("people") else \
        {"start": spans[0][0], "end": spans[0][1]}
    update(jid, exports=files, export_folder=str(folder), part=remember)
    if burn in ("zh", "both", "th"):
        _begin(jid, "burning", "Drawing the captions")
        shape = shape or {}
        update(jid, shape=shape)                 # remembered for this video
        _run(jid, _burn_job, burn, folder, base, files, shape, spans)
    return load(jid)


def _burn_job(jid, which, folder, base, files, shape=None, spans=None):
    fade = (shape or {}).get("fade", True) and spans and len(spans) > 1      # smooth joins between parts
    job = load(jid)
    d = job_dir(jid)
    m = job["media"]
    work = d / "frames"
    shutil.rmtree(work, ignore_errors=True)
    full = m.get("duration") or 0
    spans = spans or [(0.0, full)]
    all_touches = [({**t, "start": 0.0, "end": full} if t.get("whole") else t) for t in touches(jid) if not t.get("pending")]
    all_lines = lines(jid)
    W0, H0 = m.get("width") or 1920, m.get("height") or 1080
    W, H, st, plan = W0, H0, job.get("style"), None
    if (shape or {}).get("vertical"):            # 9:16 for Reels, TikTok and Shorts
        plan = style.vertical_plan(W0, H0, shape.get("fit", "fill"), shape.get("pos", 0.5))
        all_touches = [style.on_vertical(t, plan) for t in all_touches]
        W, H, st = plan["w"], plan["h"], style.vertical_style(st)
    size = (shape or {}).get("size", "full")
    label = {"zh": "中文字幕", "both": "中泰字幕", "th": "Thai captions"}[which] + (" 9x16" if plan else "") + \
        (f" {size}p" if size in media.SIZES and size != "full" else "")
    out = folder / f"{base} ({label}).mp4"
    total = sum(b - a for a, b in spans) or 1
    pieces, done = [], 0.0
    for i, (a, b) in enumerate(spans):           # each stretch on its own, then joined
        frames_dir = work / f"{i:04d}"
        whole = len(spans) == 1 and a == 0 and b >= full
        kept = all_touches if whole else _clip(all_touches, a, b)
        ls = all_lines if whole else _clip(all_lines, a, b)
        still = [t for t in kept if t.get("motion") not in style.MOTIONS]
        moving = [t for t in kept if t.get("motion") in style.MOTIONS]
        share = (b - a) / total
        lst = style.frames(ls, still, which, W, H, st, frames_dir,
                           lambda p: update(jid, progress=round(done + share * 0.3 * p, 3)), job.get("speakers"))
        moves = style.sprites(moving, W, H, st, frames_dir, b - a)
        update(jid, label="Burning captions into the video" + (f" (part {i + 1} of {len(spans)})" if len(spans) > 1 else ""))
        dst = out if len(spans) == 1 else work / f"{i:04d}.mp4"
        media.burn(d / job["source"], lst, dst, b - a, lambda p: update(jid, progress=round(done + share * (0.3 + 0.7 * p), 3)),
                   moves, plan, start=a, size=(shape or {}).get("size", "full"), canvas=(W, H),
                   fade=(fade and i > 0, fade and i < len(spans) - 1))
        pieces.append(dst)
        done += share
    if len(pieces) > 1:
        update(jid, label="Joining the parts", progress=None)
        media.join(pieces, out)
    shutil.rmtree(work, ignore_errors=True)
    files = files + [{"kind": f"video-{which}", "path": str(out)}]
    update(jid, busy=False, state="ready", label="", progress=None, exports=files)
    log(jid, f"Saved the captioned video to {str(out).replace(str(Path.home()), '~')}.", "done")


# ---------------------------------------------------------------- style and touches

def set_style(jid, st, as_default=False):
    st = {k: v for k, v in (st or {}).items() if k in style.DEFAULT}
    update(jid, style=st)
    if as_default:
        paths.save_settings({"style": st})
    return load(jid)


# ---------------------------------------------------------------- your logos (kept for every video)

LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".tif", ".tiff"}


def logos():
    out = []
    for f in sorted(paths.LOGOS.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True):
        if f.suffix.lower() in LOGO_EXT:
            meta = paths.LOGOS / (f.stem + ".json")
            info = json.loads(meta.read_text()) if meta.exists() else {}
            if "tone" not in info:
                info["tone"] = _tone(f)
                meta.write_text(json.dumps({"name": info.get("name") or f.stem, **info}, ensure_ascii=False))
            out.append({"id": f.stem, "name": info.get("name") or f.name, "file": f.name, "tone": info["tone"]})
    return out


def add_logo(filename, data):
    ext = Path(filename or "logo.png").suffix.lower()
    if ext not in LOGO_EXT:
        raise JobError("Use a picture for the logo (PNG with a see-through background works best).")
    if len(data) > 20 * 1024 * 1024:
        raise JobError("That picture is over 20 MB.")
    paths.LOGOS.mkdir(parents=True, exist_ok=True)
    lid = uuid.uuid4().hex[:8]
    (paths.LOGOS / f"{lid}{ext}").write_bytes(data)
    tone = _tone(paths.LOGOS / f"{lid}{ext}")
    (paths.LOGOS / f"{lid}.json").write_text(json.dumps({"name": Path(filename).stem, "tone": tone}, ensure_ascii=False))
    return {"id": lid, "name": Path(filename).stem, "file": f"{lid}{ext}", "tone": tone}


def _tone(f):
    """"light" or "dark": how bright the logo's visible part is (its see-through part doesn't count)."""
    try:
        from PIL import Image
        im = Image.open(f).convert("RGBA")
        im.thumbnail((200, 200))
        px = [(r, g, b) for r, g, b, a in im.getdata() if a > 128]
        if not px:
            return "light"
        lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / len(px)
        return "light" if lum > 128 else "dark"
    except Exception:
        return "light"


def remove_logo(lid):
    if not re.fullmatch(r"[0-9a-f]{8}", lid or ""):
        raise JobError("Unknown logo.")
    for f in paths.LOGOS.glob(f"{lid}.*"):
        f.unlink()


def logo_file(lid):
    if not re.fullmatch(r"[0-9a-f]{8}", lid or ""):
        raise JobError("Unknown logo.")
    f = next((f for f in paths.LOGOS.glob(f"{lid}.*") if f.suffix.lower() in LOGO_EXT), None)
    if not f:
        raise JobError("That logo is gone.")
    return f


def touches(jid):
    f = job_dir(jid) / "touches.json"
    return json.loads(f.read_text()) if f.exists() else []


def _save_touches(jid, ts):
    d = job_dir(jid)
    with _lock(jid):
        ts.sort(key=lambda t: t["start"])
        tmp = d / "touches.json.tmp"
        tmp.write_text(json.dumps(ts, ensure_ascii=False, indent=0))
        tmp.replace(d / "touches.json")
        job = load(jid)
        job["touches_rev"] = job.get("touches_rev", 0) + 1
        save(job)
    return ts


TOUCH_FIELDS = {"start", "end", "text", "x", "y", "size", "kind", "color", "outline_color", "font", "pending",
                "image", "w", "opacity", "whole", "bold", "outline", "standout", "edge", "edge_color", "plate_color",
                "motion", "period"}


def _clean_touch(t):
    t = {k: v for k, v in t.items() if k in TOUCH_FIELDS}
    for k, lo, hi in (("x", 0.0, 1.0), ("y", 0.0, 1.0), ("size", 0.3, 4.0), ("w", 0.03, 1.0), ("opacity", 0.05, 1.0),
                      ("outline", 0.0, 0.3), ("edge", 0.0, 0.06), ("period", 0.4, 20.0)):
        if k in t:
            t[k] = max(lo, min(hi, float(t[k])))
    if "start" in t:
        t["start"] = round(max(0.0, float(t["start"])), 3)
    if "end" in t:
        t["end"] = round(float(t["end"]), 3)
    return t


def add_touch(jid, t):
    t = {**style.TOUCH_DEFAULT, "x": 0.8, "y": 0.2, **_clean_touch(t), "id": uuid.uuid4().hex[:8]}
    if t.get("kind") == "image":
        if not t.get("image") or not any(paths.LOGOS.glob(f"{t['image']}.*")):
            raise JobError("Choose a logo first.")
    elif not (t.get("text") or "").strip():
        raise JobError("Type an emoji or a few words first.")
    t["end"] = max(t.get("end") or 0, t["start"] + 0.3)
    ts = touches(jid)
    ts.append(t)
    _save_touches(jid, ts)
    return t


def edit_touch(jid, tid, changes):
    ts = touches(jid)
    t = next((x for x in ts if x["id"] == tid), None)
    if not t:
        raise JobError("That touch is gone.")
    t.update(_clean_touch(changes))
    if t["end"] <= t["start"]:
        t["end"] = round(t["start"] + 0.5, 3)
    _save_touches(jid, ts)
    return t


def remove_touch(jid, tid):
    _save_touches(jid, [t for t in touches(jid) if t["id"] != tid])


# ---------------------------------------------------------------- lines you add yourself

def add_line(jid, start, end=None, th="", zh=""):
    with _lock(jid):
        ls = lines(jid)
        start = round(max(0.0, float(start)), 3)
        end = round(float(end) if end else start + 2.0, 3)
        nxt = min((l["start"] for l in ls if l["start"] > start), default=None)
        if end is None or (nxt is not None and end > nxt and nxt - start > 0.5):
            end = round(nxt - 0.04, 3)
        new = {"id": max((l["id"] for l in ls), default=0) + 1, "start": start, "end": max(end, start + 0.5),
               "th": (th or "").strip(), "zh": (zh or "").strip(), "conf": 1.0, "kind": "speech", "flag": None,
               "note": "", "status": "edited"}
        ls.append(new)
        ls.sort(key=lambda l: l["start"])
        save_lines(jid, ls)
        return new


def split_speakers(jid, lid):
    """Two people talking at once: a second line over the same time, for the other person."""
    with _lock(jid):
        ls = lines(jid)
        l = next((x for x in ls if x["id"] == lid), None)
        if not l:
            raise JobError("That line is gone.")
        people = load(jid).get("speakers") or []
        other = next((p["id"] for p in people if p["id"] != l.get("speaker")), None)
        new = {**{k: v for k, v in l.items() if k not in ("explain", "feedback", "th_before", "zh_before", "heard", "attempts")},
               "id": max(x["id"] for x in ls) + 1, "th": "", "zh": "", "speaker": other, "status": "edited", "conf": 1.0}
        ls.insert(ls.index(l) + 1, new)
        save_lines(jid, ls)
        return new


def set_speakers(jid, people):
    """People who talk, each with a caption colour and maybe their own Chinese font: [{"id", "name", "color", "font"}]."""
    clean, seen = [], set()
    for p in people or []:
        pid = str(p.get("id") or uuid.uuid4().hex[:6])
        if pid in seen:
            continue
        seen.add(pid)
        clean.append({"id": pid, "name": (p.get("name") or "").strip()[:30], "color": p.get("color") or "#FFFFFF",
                      **({"font": str(p["font"])[:60]} if p.get("font") else {})})
    with _lock(jid):
        ids = {p["id"] for p in clean}
        ls = lines(jid)
        if any(l.get("speaker") and l["speaker"] not in ids for l in ls):
            for l in ls:
                if l.get("speaker") and l["speaker"] not in ids:
                    l["speaker"] = None
            save_lines(jid, ls)
        update(jid, speakers=clean)
    memory.remember_people(clean)
    return load(jid)


def assign_speaker(jid, ids, speaker):
    """Many lines to one person at once (speaker "" clears)."""
    ids = set(int(i) for i in ids or [])
    with _lock(jid):
        ls = lines(jid)
        for l in ls:
            if l["id"] in ids:
                l["speaker"] = speaker or None
                l.pop("speaker_guess", None)
        save_lines(jid, ls)
    return len(ids)


def recognise_voices(jid):
    if not (load(jid).get("speakers") or []):
        raise JobError("Add the people first (Caption style → People).")
    _begin(jid, "speakers", "Recognising voices")
    _run(jid, _voices_job)


def _voices_job(jid):
    _recognise(jid, quiet=False)
    update(jid, busy=False, state="ready", label="", progress=None)


def _voiceprints(jid, ls):
    """Each line's voiceprint (cached in voices.npz; recomputed when a line's time changes)."""
    import numpy as np
    d = job_dir(jid)
    cache_f = d / "voices.npz"
    cache = dict(np.load(cache_f)) if cache_f.exists() else {}
    # a line's own stretch of sound: stop where the next line starts, so its voice doesn't creep in
    starts = sorted(l["start"] for l in ls)
    def span(l):
        nxt = next((t for t in starts if t > l["start"] + voices.MIN_SECONDS), l["end"])
        return l["start"], min(l["end"], nxt)
    key = lambda l: "{}_{:.2f}_{:.2f}".format(l["id"], *span(l))
    todo = [{"key": key(l), "start": span(l)[0], "end": span(l)[1]} for l in ls
            if span(l)[1] - span(l)[0] >= voices.MIN_SECONDS and key(l) not in cache]
    if todo:
        (d / "voices_todo.json").write_text(json.dumps(todo))
        wav = d / ("voice.wav" if (d / "voice.wav").exists() else "audio.wav")
        with _gpu_turn(jid):
            _sub(jid, ["ac.voices", str(wav), str(d / "voices_todo.json"), str(d / "voices_new.npz")], "Recognising voices")
        cache.update(dict(np.load(d / "voices_new.npz")))
        np.savez(cache_f, **cache)
        (d / "voices_new.npz").unlink(missing_ok=True)
    return {l["id"]: cache[key(l)] for l in ls if key(l) in cache}


def _recognise(jid, quiet=True):
    """Learn each person's voice from the lines you assigned (plus what's remembered), then give the
    unassigned lines to whoever they clearly sound like. Returns how many lines it coloured."""
    import numpy as np
    job = load(jid)
    people = job.get("speakers") or []
    if not people:
        return 0
    ls = lines(jid)
    vecs = _voiceprints(jid, ls)
    yours = [l for l in ls if l.get("speaker") and not l.get("speaker_guess") and l["id"] in vecs]
    remembered = memory.remembered_voices()
    prints, learned = {}, {}
    for p in people:
        mine = [vecs[l["id"]] for l in yours if l["speaker"] == p["id"]]
        old = remembered.get("id:" + p["id"]) or remembered.get(p.get("name"))
        if mine and p.get("name"):
            learned[p["name"]] = (voices.unit(np.mean(mine, 0)).tolist(), len(mine))
        parts = ([voices.unit(np.mean(mine, 0)) * len(mine)] if mine else []) + \
                ([np.array(old[0]) * min(old[1], 20)] if old else [])
        if parts and (len(mine) >= 2 or (old and old[1] >= 3)):
            prints[p["id"]] = voices.unit(np.sum(parts, 0))
    if not prints:
        if not quiet:
            log(jid, "To recognise voices, first give each person at least 2–3 lines "
                     "(the chip on a line, or tick lines and Assign).", "warn")
        return 0
    counts = {}
    for l in ls:
        if l.get("speaker") and not l.get("speaker_guess"):
            continue                                   # yours
        who = voices.match(vecs[l["id"]], prints) if l["id"] in vecs else None
        if who:
            l["speaker"], l["speaker_guess"] = who, "voice"
            counts[who] = counts.get(who, 0) + 1
        elif l.get("speaker_guess") == "voice":
            l["speaker"] = None
            l.pop("speaker_guess", None)
    save_lines(jid, ls)
    if learned:
        memory.remember_people(people)        # so the voices have someone to be remembered with
        memory.learn_voices(learned)
    names = {p["id"]: p.get("name") or "?" for p in people}
    left = sum(1 for l in ls if not l.get("speaker"))
    if counts or not quiet:
        log(jid, "Recognised voices: " + (", ".join(f"{names[k]} {v}" for k, v in counts.items()) or "no clear matches")
                 + f". {left} lines left for you (too short or unclear).", "done")
    return sum(counts.values())


def guess_speakers(jid):
    if not (load(jid).get("speakers") or []):
        raise JobError("Add the people first (Caption style → People).")
    _begin(jid, "speakers", "Claude is guessing who says each line")
    _run(jid, _guess_job)


def _guess_job(jid):
    job = load(jid)
    ls = lines(jid)
    r = brain.guess_speakers(job, ls, job["speakers"])
    ids = {p["id"] for p in job["speakers"]}
    by_id = {l["id"]: l for l in ls}
    n = 0
    for g in r["lines"]:
        l = by_id.get(g["id"])
        if not l or (l.get("speaker") and not l.get("speaker_guess")):     # yours stay
            continue
        if g.get("speaker") in ids:
            l["speaker"], l["speaker_guess"] = g["speaker"], True
            n += 1
    save_lines(jid, ls)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Guessed who says {n} lines (dashed chips). Correct any that are wrong.", "done")


def replace_text(jid, find, repl, where="zh", remember=False):
    """Find and replace in every line (Chinese, Thai or both); letters match whatever their case.
    remember: keep it as a rule for future videos too."""
    find, repl = (find or "").strip(), (repl or "").strip()
    if not find:
        raise JobError("Type what to find.")
    keys = {"zh": ("zh",), "th": ("th",), "both": ("th", "zh")}.get(where)
    if not keys:
        raise JobError("Choose Chinese, Thai or both.")
    pat = re.compile(re.escape(find), re.IGNORECASE)
    n_lines = n = 0
    with _lock(jid):
        ls = lines(jid)
        for l in ls:
            hit = False
            for k in keys:
                new, c = pat.subn(lambda m: repl, l.get(k) or "")
                if c:
                    l.setdefault(k + "_before", l.get(k, ""))
                    l[k], n, hit = new, n + c, True
            if hit:
                l["status"] = "edited"
                n_lines += 1
        if n:
            save_lines(jid, ls)
    learned = None
    if remember and n:
        lang = {"zh": "Chinese", "th": "Thai", "both": "the captions"}[where]
        learned = f"In {lang}, write “{repl}”, not “{find}”." if repl else f"In {lang}, leave out “{find}”."
        memory.add("rules", text=learned, source=load(jid).get("title", ""))
    return {"count": n, "lines": n_lines, "learned": learned}


def cut_line(jid, lid, at):
    """One line into two at a moment in it; the Thai and Chinese are cut at about the same place."""
    with _lock(jid):
        ls = lines(jid)
        l = next((x for x in ls if x["id"] == lid), None)
        if not l:
            raise JobError("That line is gone.")
        at = float(at)
        if not (l["start"] + 0.2 <= at <= l["end"] - 0.2):
            raise JobError("Put the playhead inside the line (not right at its edges) to split it there.")
        frac = (at - l["start"]) / (l["end"] - l["start"])
        th1, th2 = captions.split_text(l.get("th", ""), frac, thai=True)
        zh1, zh2 = captions.split_text(l.get("zh", ""), frac)
        keep = {k: v for k, v in l.items() if k not in ("explain", "feedback", "th_before", "zh_before", "heard", "attempts", "flag", "note")}
        first = {**keep, "end": round(at, 3), "th": th1, "zh": zh1, "status": "edited", "timed": "you"}
        second = {**keep, "id": max(x["id"] for x in ls) + 1, "start": round(at, 3), "th": th2, "zh": zh2, "status": "edited", "timed": "you"}
        i = ls.index(l)
        ls[i:i + 1] = [first, second]
        save_lines(jid, ls)
        return [first, second]


def join_line(jid, lid):
    """A line and the next one (by time) become one."""
    with _lock(jid):
        ls = sorted(lines(jid), key=lambda x: (x["start"], x["end"]))
        i = next((k for k, x in enumerate(ls) if x["id"] == lid), None)
        if i is None:
            raise JobError("That line is gone.")
        if i + 1 >= len(ls):
            raise JobError("This is the last line: there's nothing after it to join.")
        a, b = ls[i], ls[i + 1]
        def glue(x, y):                       # a space between, unless the first ends with punctuation (，！？)
            x, y = (x or "").strip(), (y or "").strip()
            return x + y if x and x[-1] in "，。、！？：；…）」" else " ".join(t for t in (x, y) if t)
        a.update(start=min(a["start"], b["start"]), end=max(a["end"], b["end"]), th=glue(a.get("th"), b.get("th")),
                 zh=glue(a.get("zh"), b.get("zh")), status="edited")
        if not a.get("speaker") and b.get("speaker"):
            a["speaker"] = b["speaker"]
        del ls[i + 1]
        save_lines(jid, ls)
        return a


def clear_flags(jid):
    """Every flag (and its note) off at once. Returns how many lines had one."""
    with _lock(jid):
        ls = lines(jid)
        n = 0
        for l in ls:
            if l.get("flag") or l.get("note"):
                n += bool(l.get("flag"))
                l["flag"], l["note"] = None, ""
        save_lines(jid, ls)
    return n


def delete_line(jid, lid):
    with _lock(jid):
        ls = lines(jid)
        if not any(l["id"] == lid for l in ls):
            raise JobError("That line is gone.")
        save_lines(jid, [l for l in ls if l["id"] != lid])


# ---------------------------------------------------------------- a stretch of the video, with your note

def review_range(jid, start, end, note, timing_only=False, model=None, effort=None):
    start, end = max(0.0, float(start)), float(end)
    if end - start < 0.5:
        raise JobError("Mark a stretch of at least half a second (From here / To here).")
    if end - start > 180:
        raise JobError("Mark at most 3 minutes at a time.")
    if timing_only:                           # the words are right, only the timing is off: no listening, no Claude
        _begin(jid, "timing", f"Lining up {_mmss(start)}–{_mmss(end)} with when it's said")
        _run(jid, _retime_range_job, start, end)
        return
    _begin(jid, "reviewing", f"Listening again to {_mmss(start)}–{_mmss(end)}")
    _run(jid, _review_job, start, end, (note or "").strip(), model, effort)


def _in_range(ls, start, end):
    return [l for l in ls if min(end, l["end"]) - max(start, l["start"]) > 0.5 * (l["end"] - l["start"])]


def _retime_range_job(jid, start, end):
    with _lock(jid):
        ls = lines(jid)
        ids = {l["id"] for l in _in_range(ls, start, end)}
        for l in ls:
            if l["id"] in ids:
                l.pop("timed", None)          # you asked for these to be lined up again, even ones you timed
        save_lines(jid, ls)
    moved = _retime(jid, quiet=False, only=ids)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Lined up {_mmss(start)}–{_mmss(end)} with when it's said: {moved} of {len(ids)} lines moved.", "done")


def _review_job(jid, start, end, note, model=None, effort=None):
    log(jid, f"Fixing {_mmss(start)}–{_mmss(end)} with {_with_claude(model, effort)}.")
    before = {l["id"] for l in lines(jid)}
    gone, new, explain = _review_work(jid, start, end, note)
    fresh = {l["id"] for l in lines(jid)} - before
    if fresh:
        _retime(jid, only=fresh)              # the new lines start and end with their own words
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Rebuilt {_mmss(start)}–{_mmss(end)}: {gone} old lines → {new} new. " + explain, "done")


def _review_work(jid, start, end, note, state="reviewing", why=""):
    """Listen to one stretch again several ways and have Claude rewrite its lines. Returns (old, new, explain)."""
    d = job_dir(jid)
    rd = d / "relisten"
    shutil.rmtree(rd, ignore_errors=True)
    rd.mkdir()
    a, b = max(0.0, start - 0.4), end + 0.4
    clip = rd / "range_orig.wav"           # _voice_windows looks for <id>_orig.wav
    media.cut_wav(d / "audio.wav", clip, a, b)
    main = models.mlx_path(models.listen_key())          # short clips: always the best model, even on Quicker listening
    other = "mlx-community/whisper-large-v3-mlx" if "large-v3-mlx" not in main else "mlx-community/whisper-large-v3-turbo"
    hint = ""                 # (see _relisten: a learned-word hint on a short clip gets repeated, not heard)
    plan = [{"how": "listened again (Thai)", "wav": str(clip), "model": main, "language": "th"},
            {"how": "listened again, any language", "wav": str(clip), "model": main, "language": None},
            {"how": "another model, any language", "wav": str(clip), "model": other, "language": None}]
    try:
        _step(jid, state, "Taking the music away from that stretch")
        voice = _voice_windows(jid, [("range", a, b)])[0]
        plan.append({"how": "the voice with the music removed (Thai)", "wav": str(voice), "model": main, "language": "th"})
    except Exception as e:
        log(jid, f"Couldn't remove the music for this stretch ({e}).", "warn")
    for p in plan:
        p.update(hint=hint, temperature=0.0, timed=True, offset=a)
    (rd / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
    _step(jid, state, f"Listening again to {_mmss(start)}–{_mmss(end)}", 0)
    with _gpu_turn(jid):
        _sub(jid, ["ac.relisten", str(rd / "plan.json"), str(rd / "out.json")], "Listening again")
    results = json.loads((rd / "out.json").read_text())
    attempts = [{"how": p["how"], "segments": r} for p, r in zip(plan, results) if r]

    _step(jid, state, f"Claude is rewriting {_mmss(start)}–{_mmss(end)}")
    ls = lines(jid)
    # a line belongs to the stretch when most of it is inside: one that only touches the edge
    # (its words weren't in what was listened to) stays as it is
    inside = [l for l in ls if min(end, l["end"]) - max(start, l["start"]) > 0.5 * (l["end"] - l["start"])]
    keep = [l for l in inside if locked(l)]
    job = load(jid)
    r = brain.rebuild(job, ls, start, end, inside, keep, attempts, note, job["helpers"] if why == SUBS_WHY else _check_refs(job), why)
    next_id = max((l["id"] for l in ls), default=0) + 1
    new = []
    for x in r["lines"]:
        s0, e0 = round(max(start - 0.4, float(x["start"])), 3), round(min(end + 0.4, float(x["end"])), 3)
        if e0 <= s0 or not (x.get("th") or x.get("zh")):
            continue
        guess = bool(x.get("unsure"))
        new.append({"id": next_id, "start": s0, "end": e0, "th": x.get("th", "").strip(), "zh": x.get("zh", "").strip(),
                    "conf": 0.3 if guess else 1.0, "kind": x.get("kind") or "speech", "flag": None, "note": "",
                    "status": "auto" if guess else "fixed", "explain": r.get("explain", ""), "reviewed": True,
                    # your note made these; a guessed line stays open to the self-check and redo
                    **({} if guess else {"feedback": note or ""})})
        next_id += 1
    from difflib import SequenceMatcher
    staying = [l for l in ls if l not in inside or locked(l)]
    squash = lambda t: re.sub(r"\s+", "", t or "")

    def repeats(x):                            # a kept line already says this, at about the same time
        return any(o["start"] < x["end"] + 0.5 and o["end"] > x["start"] - 0.5 and squash(x["th"]) and
                   SequenceMatcher(None, squash(x["th"]), squash(o.get("th"))).ratio() > 0.6 for o in staying)
    dropped = [x for x in new if repeats(x)]
    new = [x for x in new if x not in dropped]
    gone = {l["id"] for l in inside if not locked(l)}
    ls = [l for l in ls if l["id"] not in gone] + new
    save_lines(jid, captions.fix_timing(ls))
    if note:
        added = memory.learn(r.get("lessons"), source=load(jid).get("title", ""))
        if added:
            log(jid, "Learned for next time: " + "; ".join(x.get("rule") or f"{x.get('th')} → {x.get('zh')}" for x in added), "learn")
    return len(gone), len(new), r.get("explain") or ""


# ---------------------------------------------------------------- talking with no captions

SUBS_WHY = "the video's own subtitles show someone talking here, but there were no captions for it"
_NOT_WORDS = re.compile(r"[\[(（【][^\])）】]*[\])）】]|[♪♫#*\-–—.,!?…'\"\s]")


def subtitle_gaps(jid):
    """Stretches where subtitles written by people (the video's own captions, burned-in subtitles, your timed
    helpers) show talking but no caption covers it: what the listening dropped. [(start, end)]."""
    job = load(jid)
    ls = [l for l in lines(jid) if l.get("kind") != "sound" and (l.get("th") or "").strip()]
    dur = (job.get("media") or {}).get("duration") or 1e9

    def covered(a, b):              # lines a little wider: the two are timed by different people
        return sum(max(0.0, min(b, l["end"] + 0.3) - max(a, l["start"] - 0.3)) for l in ls) / (b - a)
    gaps = []
    for h in job["helpers"]:
        shift = track_shift(h.get("items") or [], ls)
        for c in h.get("items") or []:
            a, b = float(c["start"]) + shift, min(float(c["end"]) + shift, dur)
            words = _NOT_WORDS.sub("", c.get("text") or "")      # "[Music]", "(laughs)", "♪" aren't talking
            if b - a >= 0.8 and len(words) >= 2 and covered(a, b) < 0.3:
                gaps.append([a, b])
    return _merge_gaps(gaps, join=1.5, longest=60)


def track_shift(cues, ls, most=6.0):
    """Subtitles timed against another cut of the video (an intro added or trimmed) are early or late all the
    way through: the shift in seconds that lines them up best with the captions, 0 when they already fit."""
    if len(cues) < 5 or len(ls) < 5:
        return 0.0
    import numpy as np
    step = 0.25
    n = int((max(max(c["end"] for c in cues), max(l["end"] for l in ls)) + most) / step) + 2

    def mask(items):
        m = np.zeros(n, dtype=np.int32)
        for x in items:
            m[max(0, int(float(x["start"]) / step)):max(0, int(float(x["end"]) / step))] = 1
        return m
    cm, lm = mask(cues), mask(ls)
    k = int(most / step)
    scores = {d: int((np.roll(cm, d)[k:n - k] & lm[k:n - k]).sum()) for d in range(-k, k + 1)}
    best = max(scores, key=lambda d: (scores[d], -abs(d)))
    return best * step if scores[best] > 1.15 * scores[0] else 0.0     # only a clear improvement moves them


def _merge_gaps(gaps, join, longest):
    merged = []
    for a, b in sorted(gaps):
        if merged and a - merged[-1][1] < join and b - merged[-1][0] < longest:
            merged[-1][1] = max(merged[-1][1], b)
        elif merged and a < merged[-1][1]:            # overlaps but would grow too long: carry on after it
            if b > merged[-1][1]:
                merged.append([merged[-1][1], b])
        else:
            merged.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in merged]


def _retime(jid, quiet=True, only=None):
    """Every line's timing from where its own letters are heard (ac/align.py), not shared out by length.
    Lines you timed yourself stay where you put them. Never stops the run (quiet) unless asked."""
    d = job_dir(jid)
    ls = lines(jid)
    todo = [l for l in ls if l.get("timed") != "you" and (l.get("th") or "").strip() and l.get("kind") != "sound"
            and (only is None or l["id"] in only)]
    if not todo:
        return 0
    try:
        (d / "align_in.json").write_text(json.dumps(todo, ensure_ascii=False))
        _step(jid, load(jid)["state"], "Lining up each caption with when it's said", 0)
        with _gpu_turn(jid):
            _sub(jid, ["ac.align", str(d / "audio.wav"), str(d / "align_in.json"), str(d / "align_out.json")],
                 "Lining up each caption with when it's said")
        found = {int(k): v for k, v in json.loads((d / "align_out.json").read_text()).items()}
    except procs.Stopped:
        raise
    except Exception as e:
        if not quiet:
            raise
        log(jid, f"Couldn't line up the timing this time ({e}); the captions keep their times.", "warn")
        return 0
    finally:
        for f in ("align_in.json", "align_out.json"):
            (d / f).unlink(missing_ok=True)
    with _lock(jid):
        ls = lines(jid)                       # fresh: you may have edited meanwhile
        was = {l["id"]: (l["start"], l["end"]) for l in ls}
        moved = 0
        for l in ls:
            if l["id"] in found and l.get("timed") != "you":
                a, b = found[l["id"]][0], found[l["id"]][1]
                if abs(a - l["start"]) > 0.05 or abs(b - l["end"]) > 0.05:
                    moved += 1
                l["start"], l["end"] = max(0.0, a), b
        ls = captions.fix_timing(ls)          # short lines stay up long enough to read…
        ls.sort(key=lambda l: (l["start"], l["end"]))
        # …but a line's tail may not run into the next line, unless the two overlapped before (people talking at once)
        for x, y in zip(ls, ls[1:]):
            wx, wy = was.get(x["id"]), was.get(y["id"])
            talked_over = wx and wy and wx[1] > wy[0] + 0.3
            if x["end"] > y["start"] and not talked_over and x.get("timed") != "you":
                x["end"] = round(max(x["start"] + 0.3, y["start"] - 0.02), 3)
        save_lines(jid, ls)
    if only is None:
        log(jid, f"Lined up the timing of {moved} captions with when they're actually said.")
    return moved


def retime(jid):
    """The button: line up every caption's timing with the speech (lines you timed yourself stay)."""
    _begin(jid, "timing", "Lining up each caption with when it's said")
    _run(jid, _retime_job)


def _retime_job(jid):
    _retime(jid, quiet=False)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, "Timing lined up. Lines you timed yourself were left as they were.", "done")


# ---------------------------------------------------------------- careful: the weak spots, fixed like Fix a stretch

CAREFUL_PER_HOUR = 15         # how many stretches a careful pass rebuilds per hour of video (at least 3)
CAREFUL_MIN_SCORE = 2.0       # a stretch needs at least this much evidence (two signs) to be worth it


def weak_spots(jid, limit=None):
    """The stretches most likely to be wrong: [(start, end, why)], worst first. Signs per line (not lines you typed):
    the listening wasn't sure, Claude thinks it's misheard, two people talk at once, too fast to read, or a long
    line holding few words for the talking under it."""
    job = load(jid)
    ls = sorted(lines(jid), key=lambda l: l["start"])
    dur = (job.get("media") or {}).get("duration") or (ls[-1]["end"] if ls else 0)
    marks = []
    for i, l in enumerate(ls):
        if locked(l) or l.get("kind") == "sound":
            continue
        signs = []
        if l.get("status") == "auto" and l.get("conf", 1) < UNSURE:
            signs.append("words it wasn't sure of")
        if l.get("suspect"):
            signs.append("words that look misheard")
        if any(o is not l and not locked(o) and o["start"] < l["end"] - 0.3 and o["end"] > l["start"] + 0.3
               for o in ls[max(0, i - 3):i + 4]):          # (a talk-over you split yourself is already handled)
            signs.append("two people talking at once")
        zh = re.sub(r"[\s，。、！？：；…（）「」,.!?:;()]", "", l.get("zh") or "")
        d = max(0.05, l["end"] - l["start"])
        if zh and len(zh) / d > 9:
            signs.append("lines too fast to read")
        if d > 5 and captions.visible_len(l.get("th") or "") / d < THIN_LETTERS_PER_SECOND:
            signs.append("talking with too few words")
        if signs:
            marks.append((l["start"], l["end"], signs))
    spans = []                                 # nearby doubtful lines make one stretch (up to a minute)
    for a, b, signs in marks:
        if spans and a - spans[-1][1] < 4 and b - spans[-1][0] < 60:
            spans[-1][1] = max(spans[-1][1], b)
            spans[-1][2] += signs
        else:
            spans.append([a, b, list(signs)])
    scored = []
    for a, b, signs in spans:
        score = len(signs) - 0.5 * signs.count("lines too fast to read")
        if score >= CAREFUL_MIN_SCORE:
            kinds = sorted(set(signs), key=signs.index)
            prev = max((l["end"] for l in ls if l["end"] <= a + 0.01), default=0.0)
            nxt = min((l["start"] for l in ls if l["start"] >= b - 0.01), default=dur or b + 0.8)
            scored.append((score, max(0.0, prev, a - 0.8), min(nxt, b + 0.8), ", ".join(kinds)))
    scored.sort(key=lambda x: -x[0])
    n = limit or max(3, round(CAREFUL_PER_HOUR * (dur or 0) / 3600))
    return [(round(a, 2), round(b, 2), why) for _, a, b, why in sorted(scored[:n], key=lambda x: x[1])]


def _careful(jid, quiet=True):
    """Fix a stretch, done for you on the weak spots. Never stops the run (quiet) unless asked. The timing is lined up
    first: the spots are cut by time, and lines a second or two late would send it listening in the wrong place."""
    _retime(jid)
    spots = weak_spots(jid)
    if not spots:
        log(jid, "Careful pass: no weak spots stood out.")
        return 0
    log(jid, f"Careful pass: listening again to {len(spots)} weak spot{'s' if len(spots) > 1 else ''}: "
             + "; ".join(f"{_mmss(a)}–{_mmss(b)} ({why})" for a, b, why in spots[:8]) + ("…" if len(spots) > 8 else ""))
    before = {l["id"] for l in lines(jid)}
    done = 0
    for i, (a, b, why) in enumerate(spots):
        _step(jid, load(jid)["state"], f"Careful pass: fixing weak spot {i + 1} of {len(spots)} ({_mmss(a)}–{_mmss(b)})")
        try:
            _review_work(jid, a, b, "", state=load(jid)["state"], why=f"the first pass looked doubtful here ({why})")
            done += 1
        except procs.Stopped:
            raise
        except Exception as e:
            if not quiet:
                raise
            log(jid, f"Couldn't fix {_mmss(a)}–{_mmss(b)} ({e}).", "warn")
    fresh = {l["id"] for l in lines(jid)} - before
    if fresh:
        _retime(jid, only=fresh)
    log(jid, f"Careful pass: rebuilt {done} weak spot{'s' if done != 1 else ''}.")
    return done


def fix_weak_spots(jid):
    """The button (More → Fix the weak spots): the careful pass on a finished video."""
    if not weak_spots(jid):
        raise JobError("No weak spots stand out: no stretches with several doubtful lines.")
    _begin(jid, "checking", "Finding the weak spots")
    _run(jid, _weak_spots_job)


def _weak_spots_job(jid):
    n = _careful(jid, quiet=True)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Fixed {n} weak spot{'s' if n != 1 else ''}. They're marked as fixed: check them.", "done")


def _check_refs(job):
    """Subtitles written by people, for the checks: only when "Also check the captions against them" is on."""
    return job["helpers"] if job["options"].get("subs_check") else []


def _fill_from_subtitles(jid):
    """Listen again where the video's subtitles show talking the captions are missing. Never stops the run."""
    if not load(jid)["options"].get("subs_check"):
        return
    try:
        gaps = subtitle_gaps(jid)
    except Exception as e:
        log(jid, f"Couldn't compare with the video's own subtitles ({e}).", "warn")
        return
    if not gaps:
        return
    todo = gaps[:SUBS_FILL_MAX]
    log(jid, f"The video's own subtitles show talking in {len(gaps)} place{'s' if len(gaps) > 1 else ''} with no captions: "
             + ", ".join(f"{_mmss(a)}–{_mmss(b)}" for a, b in gaps[:12]) + ("…" if len(gaps) > 12 else "") + ". Listening again.")
    added = 0
    for i, (a, b) in enumerate(todo):
        _step(jid, "checking", f"Filling in talking the subtitles show ({i + 1} of {len(todo)})")
        try:
            _, new, _ = _review_work(jid, a, b, "", state="checking", why=SUBS_WHY)
            added += new
        except procs.Stopped:
            raise
        except Exception as e:
            log(jid, f"Couldn't fill in {_mmss(a)}–{_mmss(b)} ({e}).", "warn")
    log(jid, f"Filled in {added} lines the listening had missed." +
             (f" {len(gaps) - len(todo)} more places are left: press Find skipped talking." if len(gaps) > len(todo) else ""))


def skipped_speech(jid):
    """Stretches where the voice detector hears talking but no real caption covers it (a "(music)" marker
    doesn't count). [(start, end)], merged when close, each at most 2 minutes."""
    d = job_dir(jid)
    from . import listen
    x = listen.load_wav(d / ("voice.wav" if (d / "voice.wav").exists() else "audio.wav"))
    parts = listen.speech_parts(x, 0.8, max_chunk=12)
    ls = [l for l in lines(jid) if l.get("kind") != "sound" and (l.get("th") or "").strip()]

    def covered(a, b):
        return sum(max(0.0, min(b, l["end"]) - max(a, l["start"])) for l in ls) / (b - a)

    def letters_per_second(a, b):
        # captions over this stretch, each counted by how much of it falls inside
        n = sum(captions.visible_len(l["th"]) * max(0.0, min(b, l["end"]) - max(a, l["start"])) / max(0.1, l["end"] - l["start"])
                for l in ls)
        return n / (b - a)
    gaps = []
    for a, b in parts:
        # no captions, or far too few words for this much talking (a line stretched over speech that
        # was lost: Thai speech is 8-14 letters a second, a thin line covering it gives under 4)
        if b - a > 1.5 and (covered(a, b) < 0.35 or (b - a > 4 and letters_per_second(a, b) < THIN_LETTERS_PER_SECOND)):
            gaps.append([a, b])
    # one line stretched over a lot of talking but holding few words
    talking = lambda a, b: sum(max(0.0, min(b, e) - max(a, s)) for s, e in parts) / max(0.1, b - a)
    for l in ls:
        dur = l["end"] - l["start"]
        if dur > 5 and captions.visible_len(l["th"]) / dur < THIN_LETTERS_PER_SECOND and talking(l["start"], l["end"]) > 0.6:
            gaps.append([l["start"], l["end"]])
    gaps += [list(g) for g in subtitle_gaps(jid)]
    return _merge_gaps(gaps, join=1.5, longest=120)


def fill_skipped(jid):
    _begin(jid, "filling", "Looking for talking with no captions")
    _run(jid, _fill_job)


def _fill_job(jid):
    _step(jid, "filling", "Looking for talking with no captions")
    gaps = skipped_speech(jid)
    sub_gaps = subtitle_gaps(jid)
    if not gaps:
        update(jid, busy=False, state="ready", label="", progress=None)
        log(jid, "No skipped talking found: every stretch of speech has captions.", "done")
        return
    log(jid, f"Found {len(gaps)} stretch{'es' if len(gaps) > 1 else ''} of talking with no captions: "
             + ", ".join(f"{_mmss(a)}–{_mmss(b)}" for a, b in gaps) + ".")
    added = 0
    for i, (a, b) in enumerate(gaps):
        _step(jid, "filling", f"Listening again to {_mmss(a)}–{_mmss(b)} ({i + 1} of {len(gaps)})")
        _, new, _ = _review_work(jid, a, b, "", state="filling",
                                 why=SUBS_WHY if any(x < b and a < y for x, y in sub_gaps) else "")
        added += new
    _auto_voices(jid)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Filled in the skipped talking: {added} new lines in {len(gaps)} stretches. Check them; they're marked as fixed.", "done")


# ---------------------------------------------------------------- cute touches, suggested by Claude

def suggest_touches(jid):
    _begin(jid, "touches", "Looking at the video for moments worth a touch")
    _run(jid, _suggest_job)


def _suggest_job(jid):
    job = load(jid)
    d = job_dir(jid)
    sheets_dir = d / "sheets"
    shutil.rmtree(sheets_dir, ignore_errors=True)
    dur = job["media"].get("duration") or 0
    every = max(2, min(10, round(dur / 120)))
    sheets = media.contact_sheets(d / job["source"], sheets_dir, every)
    _step(jid, "touches", "Claude is picking moments for emoji and notes")
    r = brain.suggest_touches(job, lines(jid), sheets, every)
    ts = touches(jid)
    ts = [t for t in ts if not t.get("pending")]          # a new round replaces the old suggestions
    for x in r["touches"]:
        t = _clean_touch({**x, "pending": True})
        t["end"] = max(t.get("end", 0), t["start"] + 1.0)
        ts.append({**style.TOUCH_DEFAULT, **t, "why": x.get("why", ""), "id": uuid.uuid4().hex[:8]})
    _save_touches(jid, ts)
    shutil.rmtree(sheets_dir, ignore_errors=True)
    update(jid, busy=False, state="ready", label="", progress=None)
    log(jid, f"Suggested {len(r['touches'])} touches. Keep the ones you like.", "done")
