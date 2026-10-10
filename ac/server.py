"""Local web app: python -m ac  ->  http://127.0.0.1:8771"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, fetch, jobs, media, memory, models, paths, style

PORT = int(os.environ.get("AC_PORT", 8771))
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

app = FastAPI(title="AutoCaption", docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Only this Mac's browser may drive the app: other websites can't reach it
    # through DNS tricks (Host check) or cross-site form posts (custom header).
    if request.headers.get("host") not in HOSTS and not os.environ.get("AC_TEST"):
        return JSONResponse({"error": "Open the app at http://127.0.0.1:%d" % PORT}, 403)
    if request.method not in ("GET", "HEAD") and request.headers.get("x-ac") != "1":
        return JSONResponse({"error": "Requests must come from the AutoCaption page."}, 403)
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        # the page's own files: always check for a newer copy (Safari otherwise keeps running
        # yesterday's app.js after an update, even across reloads)
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(jobs.JobError)
@app.exception_handler(fetch.FetchError)
@app.exception_handler(media.MediaError)
@app.exception_handler(brain.BrainError)
@app.exception_handler(ValueError)
async def friendly(_request, exc):
    return JSONResponse({"error": str(exc)}, 400)


def _code_stamp():
    """When the app's own code last changed on disk."""
    return max((f.stat().st_mtime for f in Path(__file__).parent.glob("*.*") if f.suffix in (".py", ".swift")), default=0)


CODE_AT_START = _code_stamp()


@app.get("/api/status")
def status():
    # stale: the app was updated after it started; the page asks you to reopen it (new buttons need the new code)
    return {"claude": bool(paths.claude()), "out": str(paths.OUT).replace(str(Path.home()), "~"),
            "burn": "ffmpeg-full" in paths.ffmpeg(), "stale": _code_stamp() > CODE_AT_START + 1}


# ---------------------------------------------------------------- jobs

class LinkIn(BaseModel):
    url: str
    about: str = ""
    clean_voice: bool = False
    fast: bool = False
    video_subs: bool = True
    subs_check: bool = False
    careful: bool = False


@app.post("/api/jobs")
def new_job(body: LinkIn):
    return jobs.create_from_link(body.url, body.about, body.clean_voice, body.fast, body.video_subs, body.subs_check, body.careful)


@app.post("/api/jobs/upload")
def upload_job(file: UploadFile = File(...), about: str = Form(""), clean_voice: bool = Form(False),
               fast: bool = Form(False), video_subs: bool = Form(True), subs_check: bool = Form(False),
               careful: bool = Form(False)):
    return jobs.create_from_upload(file.filename, file.file, about, clean_voice, fast, video_subs, subs_check, careful)


@app.get("/api/jobs")
def all_jobs():
    return jobs.listing()


@app.get("/api/jobs/{jid}")
def one_job(jid: str):
    return jobs.load(jid)


@app.delete("/api/jobs/{jid}")
def remove_job(jid: str):
    jobs.delete(jid)
    return {"ok": True}


@app.get("/api/jobs/{jid}/lines")
def get_lines(jid: str):
    return jobs.lines(jid)


class LineIn(BaseModel):
    speaker: str | None = None
    th: str | None = None
    zh: str | None = None
    start: float | None = None
    end: float | None = None
    flag: str | None = None
    note: str | None = None
    look: dict | None = None


@app.patch("/api/jobs/{jid}/lines/{lid}")
def edit_line(jid: str, lid: int, body: LineIn):
    return jobs.edit_line(jid, lid, body.model_dump(exclude_unset=True))


class FixIn(BaseModel):
    model: str | None = None
    effort: str | None = None


@app.post("/api/jobs/{jid}/fix")
def fix(jid: str, body: FixIn | None = None):
    jobs.fix_flagged(jid, body.model if body else None, body.effort if body else None)
    return jobs.load(jid)


class RedoIn(BaseModel):
    what: str = "all"


@app.post("/api/jobs/{jid}/redo")
def redo(jid: str, body: RedoIn):
    jobs.redo(jid, body.what)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/stop")
def stop(jid: str):
    return jobs.stop(jid)


@app.get("/api/jobs/{jid}/usage")
def job_usage(jid: str):
    return brain.usage(jobs.job_dir(jid))


@app.post("/api/jobs/{jid}/retry")
def retry(jid: str):
    jobs.retry(jid)
    return jobs.load(jid)


class AgainIn(BaseModel):
    clean_voice: bool = True


@app.post("/api/jobs/{jid}/listen-again")
def listen_again(jid: str, body: AgainIn):
    jobs.listen_again(jid, body.clean_voice)
    return jobs.load(jid)


@app.get("/api/jobs/{jid}/waveform")
def waveform(jid: str):
    return Response(jobs.waveform(jid), media_type="application/octet-stream",
                    headers={"X-Rate": str(jobs.WAVE_RATE), "Cache-Control": "no-cache"})


@app.get("/api/jobs/{jid}/video")
def video(jid: str):
    return FileResponse(jobs.job_dir(jid) / "preview.mp4", media_type="video/mp4")


@app.post("/api/jobs/{jid}/helpers")
async def add_helper(jid: str, kind: str = Form(...), label: str = Form(""), text: str = Form(""),
                     files: list[UploadFile] = File(default=[])):
    got = []
    for f in files:
        data = await f.read()
        if len(data) > 30 * 1024 * 1024:
            raise ValueError(f"{f.filename} is over 30 MB.")
        got.append((f.filename or "file", data))
    return jobs.add_helper(jid, kind, label, got, text)


@app.delete("/api/jobs/{jid}/helpers/{hid}")
def remove_helper(jid: str, hid: str):
    jobs.remove_helper(jid, hid)
    return jobs.load(jid)


@app.get("/api/jobs/{jid}/helpers/{name}")
def helper_picture(jid: str, name: str):
    p = jobs.job_dir(jid) / "helpers" / Path(name).name
    if not p.exists():
        raise ValueError("No such picture.")
    return FileResponse(p)


class ExportIn(BaseModel):
    srt: bool = True
    burn: str = "zh"          # zh | both | th | none
    shape: dict | None = None  # {"vertical": true, "fit": "fill" | "fit", "pos": 0..1}
    part: dict | None = None   # {"start", "end"}: just this part of the video


@app.post("/api/jobs/{jid}/export")
def export(jid: str, body: ExportIn):
    return jobs.export(jid, body.srt, body.burn, body.shape, body.part)


class StyleIn(BaseModel):
    style: dict
    as_default: bool = False


@app.post("/api/jobs/{jid}/style")
def set_style(jid: str, body: StyleIn):
    return jobs.set_style(jid, body.style, body.as_default)


class NewLineIn(BaseModel):
    start: float
    end: float | None = None
    th: str = ""
    zh: str = ""


@app.post("/api/jobs/{jid}/lines")
def add_line(jid: str, body: NewLineIn):
    return jobs.add_line(jid, body.start, body.end, body.th, body.zh)


class ReplaceIn(BaseModel):
    find: str
    replace: str = ""
    where: str = "zh"
    remember: bool = False


@app.post("/api/jobs/{jid}/replace")
def replace_text(jid: str, body: ReplaceIn):
    return jobs.replace_text(jid, body.find, body.replace, body.where, body.remember)


class CutIn(BaseModel):
    at: float


@app.post("/api/jobs/{jid}/lines/{lid}/cut")
def cut_line(jid: str, lid: int, body: CutIn):
    return jobs.cut_line(jid, lid, body.at)


@app.get("/api/jobs/{jid}/weak-spots")
def weak_spots(jid: str):
    return [{"start": a, "end": b, "why": why} for a, b, why in jobs.weak_spots(jid)]


@app.post("/api/jobs/{jid}/weak-spots")
def fix_weak_spots(jid: str):
    jobs.fix_weak_spots(jid)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/retime")
def retime(jid: str):
    jobs.retime(jid)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/lines/{lid}/join")
def join_line(jid: str, lid: int):
    return jobs.join_line(jid, lid)


@app.post("/api/jobs/{jid}/lines/{lid}/split")
def split_line(jid: str, lid: int):
    return jobs.split_speakers(jid, lid)


class SpeakersIn(BaseModel):
    speakers: list[dict]


@app.post("/api/jobs/{jid}/speakers")
def set_speakers(jid: str, body: SpeakersIn):
    return jobs.set_speakers(jid, body.speakers)


class AssignIn(BaseModel):
    ids: list[int]
    speaker: str = ""


@app.post("/api/jobs/{jid}/assign")
def assign(jid: str, body: AssignIn):
    return {"assigned": jobs.assign_speaker(jid, body.ids, body.speaker)}


@app.post("/api/jobs/{jid}/recognise-voices")
def recognise_voices(jid: str):
    jobs.recognise_voices(jid)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/guess-speakers")
def guess_speakers(jid: str):
    jobs.guess_speakers(jid)
    return jobs.load(jid)


@app.delete("/api/jobs/{jid}/lines/{lid}")
def delete_line(jid: str, lid: int):
    jobs.delete_line(jid, lid)
    return {"ok": True}


class RangeIn(BaseModel):
    start: float
    end: float
    note: str = ""
    timing_only: bool = False     # just line up the timing there (no listening again, no Claude)
    model: str | None = None      # this fix only: a Claude model and effort (else the ones under Models)
    effort: str | None = None


@app.post("/api/jobs/{jid}/video-subs")
def video_subs(jid: str):
    jobs.find_video_subs(jid)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/fill-skipped")
def fill_skipped(jid: str):
    jobs.fill_skipped(jid)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/review")
def review(jid: str, body: RangeIn):
    jobs.review_range(jid, body.start, body.end, body.note, body.timing_only, body.model, body.effort)
    return jobs.load(jid)


@app.get("/api/logos")
def get_logos():
    return jobs.logos()


@app.post("/api/logos")
async def upload_logo(file: UploadFile = File(...)):
    return jobs.add_logo(file.filename, await file.read())


@app.get("/api/logos/{lid}")
def logo_image(lid: str):
    return FileResponse(jobs.logo_file(lid))


@app.delete("/api/logos/{lid}")
def delete_logo(lid: str):
    jobs.remove_logo(lid)
    return {"ok": True}


@app.get("/api/jobs/{jid}/touches")
def get_touches(jid: str):
    return jobs.touches(jid)


@app.post("/api/jobs/{jid}/touches")
def add_touch(jid: str, body: dict):
    return jobs.add_touch(jid, body)


@app.post("/api/jobs/{jid}/touches/suggest")
def suggest_touches(jid: str):
    jobs.suggest_touches(jid)
    return jobs.load(jid)


@app.patch("/api/jobs/{jid}/touches/{tid}")
def edit_touch(jid: str, tid: str, body: dict):
    return jobs.edit_touch(jid, tid, body)


@app.delete("/api/jobs/{jid}/touches/{tid}")
def remove_touch(jid: str, tid: str):
    jobs.remove_touch(jid, tid)
    return {"ok": True}


# ---------------------------------------------------------------- settings: models and default style

@app.get("/api/fonts/{name}")
def font_file(name: str):
    """One of the free fonts (only those), for the page's @font-face: Safari won't use installed fonts."""
    known = {f for _, f, _ in style.FREE_FONTS}
    if name in known and (style.USER_FONTS / name).exists():
        path = style.USER_FONTS / name
    else:
        path = style.system_font_file(name)          # one of the Mac's own fonts the page can't use by itself
        if not path:
            raise HTTPException(404, "Not one of the caption fonts.")
    return FileResponse(path, media_type="font/otf" if path.suffix.lower() == ".otf" else "font/ttf",
                        headers={"Cache-Control": "max-age=604800"})


@app.get("/api/settings")
def get_settings():
    s = paths.load_settings()
    return {
        "listen_model": models.listen_key(), "claude_model": models.claude_model(),
        "claude_effort": s.get("claude_effort") or "auto",
        "efforts": [{"key": k, **v} for k, v in models.EFFORTS.items()],
        "clean_voice": bool(s.get("clean_voice")), "fast": bool(s.get("fast")), "video_subs": s.get("video_subs", True), "subs_check": bool(s.get("subs_check")), "careful": bool(s.get("careful")),
        "listen_models": [{"key": k, **{x: v[x] for x in ("label", "about")}, "ready": models.is_ready(k)}
                          for k, v in models.LISTEN.items()],
        "claude_models": [{"key": k, **v} for k, v in models.CLAUDE.items()],
        "style": style.merged(s.get("style")), "style_default": style.DEFAULT,
        "themes": [{"key": k, "label": v["label"], "style": style.merged({"theme": k})} for k, v in style.THEMES.items()],
        "fonts": _fonts(), "font_faces": style.free_font_faces() + [{k: f[k] for k in ("family", "file", "weight")} for f in style.system_font_faces()],
    }


_font_cache = {}


def _fonts():
    if "f" not in _font_cache:
        try:
            _font_cache["f"] = style.available_fonts()
        except Exception:
            _font_cache["f"] = {"zh": [{"family": f, "label": l} for f, l in style.ZH_FONTS[:3]],
                                "th": [{"family": f, "label": l} for f, l in style.TH_FONTS[:2]]}
    return _font_cache["f"]


class SettingsIn(BaseModel):
    listen_model: str | None = None
    claude_model: str | None = None
    claude_effort: str | None = None


@app.post("/api/settings")
def set_settings(body: SettingsIn):
    ch = {}
    if body.listen_model:
        if body.listen_model not in models.LISTEN:
            raise ValueError("Unknown listening model.")
        ch["listen_model"] = body.listen_model
    if body.claude_model:
        if body.claude_model not in models.CLAUDE:
            raise ValueError("Unknown Claude model.")
        ch["claude_model"] = body.claude_model
    if body.claude_effort:
        if body.claude_effort not in models.EFFORTS:
            raise ValueError("Unknown effort level.")
        ch["claude_effort"] = body.claude_effort
    paths.save_settings(ch)
    return get_settings()


# ---------------------------------------------------------------- memory

@app.get("/api/memory")
def get_memory():
    return memory.load()


class MemoryIn(BaseModel):
    kind: str                 # names | words | rules | people
    color: str = ""
    th: str = ""
    zh: str = ""
    text: str = ""
    note: str = ""


@app.post("/api/memory")
def add_memory(body: MemoryIn):
    if body.kind == "people":
        if not body.text.strip():
            raise ValueError("Type the person's name.")
        memory.remember_people([{"name": body.text.strip(), "color": body.color or "#FFE14D"}])
        return memory.load()
    if body.kind not in ("names", "words", "rules"):
        raise ValueError("Unknown kind.")
    return memory.add(body.kind, body.th, body.zh, body.text, body.note, source="added by hand")


class MemoryEditIn(BaseModel):
    name: str | None = None
    color: str | None = None
    th: str | None = None
    zh: str | None = None
    text: str | None = None
    note: str | None = None


@app.patch("/api/memory/{kind}/{eid}")
def edit_memory(kind: str, eid: str, body: MemoryEditIn):
    return memory.edit(kind, eid, body.model_dump(exclude_none=True))


@app.post("/api/memory/people/{pid}/forget-voice")
def forget_voice(pid: str):
    return memory.forget_voice(pid)


@app.delete("/api/memory/{kind}/{eid}")
def delete_memory(kind: str, eid: str):
    return memory.remove(kind, eid)


# ---------------------------------------------------------------- Finder

class PathIn(BaseModel):
    path: str


@app.post("/api/reveal")
def reveal(body: PathIn):
    p = Path(body.path).expanduser()
    if not p.exists() or paths.OUT not in p.parents:
        raise ValueError("That file isn't there any more.")
    subprocess.run(["open", "-R", str(p)], check=False)
    return {"ok": True}


class QuitIn(BaseModel):
    force: bool = False


@app.post("/api/quit")
def quit_app(body: QuitIn):
    """Close AutoCaption (the page's Quit button, or a newer copy starting). Not while a video is being worked on,
    unless forced: that step would have to be run again."""
    busy = [j for j in jobs.listing() if j.get("busy")]
    if busy and not body.force:
        raise HTTPException(409, "A video is still being worked on (" + (busy[0].get("title") or "a video")[:60] + ").")
    for j in busy:
        jobs.stop(j["id"])

    def bye():
        if style.renderer.proc and style.renderer.proc.poll() is None:
            style.renderer.proc.kill()
        os._exit(0)
    threading.Timer(0.4, bye).start()
    return {"ok": True}


app.mount("/", StaticFiles(directory=paths.WEB, html=True), name="web")


def _already_running(url):
    """The AutoCaption already running here, if any: its /api/status."""
    import urllib.request
    try:
        with urllib.request.urlopen(url + "api/status", timeout=1) as r:
            return json.loads(r.read()) if r.status == 200 else None
    except (OSError, ValueError):
        return None


def _ask_to_quit(url):
    """Ask the AutoCaption that's running to close (it says no while it's busy). True when it has gone."""
    import time
    import urllib.request
    req = urllib.request.Request(url + "api/quit", data=b"{}", method="POST",
                                 headers={"x-ac": "1", "content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except OSError:
        return False
    for _ in range(30):
        time.sleep(0.2)
        if _already_running(url) is None:
            return True
    return False


def main():
    import uvicorn
    paths.ensure_dirs()
    url = f"http://127.0.0.1:{PORT}/"
    if _already_running(url) is not None:
        # an AutoCaption is already running (maybe an older one, maybe with no window): this one takes over,
        # with the newest code, unless that one is busy with a video
        if not _ask_to_quit(url):
            print(f"AutoCaption is already running at {url} and is busy with a video, so that one stays open.")
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
            return
        print("Closed the AutoCaption that was already running; starting this one.")
    jobs.recover_interrupted()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"AutoCaption is running at {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
