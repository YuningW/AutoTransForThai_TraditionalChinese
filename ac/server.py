"""Local web app: python -m ac  ->  http://127.0.0.1:8771"""
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, fetch, jobs, media, memory, paths

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
    return await call_next(request)


@app.exception_handler(jobs.JobError)
@app.exception_handler(fetch.FetchError)
@app.exception_handler(media.MediaError)
@app.exception_handler(brain.BrainError)
@app.exception_handler(ValueError)
async def friendly(_request, exc):
    return JSONResponse({"error": str(exc)}, 400)


@app.get("/api/status")
def status():
    return {"claude": bool(paths.claude()), "out": str(paths.OUT).replace(str(Path.home()), "~"),
            "burn": "ffmpeg-full" in paths.ffmpeg()}


# ---------------------------------------------------------------- jobs

class LinkIn(BaseModel):
    url: str
    about: str = ""
    clean_voice: bool = False
    fast: bool = False


@app.post("/api/jobs")
def new_job(body: LinkIn):
    return jobs.create_from_link(body.url, body.about, body.clean_voice, body.fast)


@app.post("/api/jobs/upload")
def upload_job(file: UploadFile = File(...), about: str = Form(""), clean_voice: bool = Form(False),
               fast: bool = Form(False)):
    return jobs.create_from_upload(file.filename, file.file, about, clean_voice, fast)


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
    th: str | None = None
    zh: str | None = None
    start: float | None = None
    end: float | None = None
    flag: str | None = None
    note: str | None = None


@app.patch("/api/jobs/{jid}/lines/{lid}")
def edit_line(jid: str, lid: int, body: LineIn):
    return jobs.edit_line(jid, lid, body.model_dump(exclude_unset=True))


@app.post("/api/jobs/{jid}/fix")
def fix(jid: str):
    jobs.fix_flagged(jid)
    return jobs.load(jid)


class RedoIn(BaseModel):
    what: str = "all"


@app.post("/api/jobs/{jid}/redo")
def redo(jid: str, body: RedoIn):
    jobs.redo(jid, body.what)
    return jobs.load(jid)


@app.post("/api/jobs/{jid}/retry")
def retry(jid: str):
    jobs.retry(jid)
    return jobs.load(jid)


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
    size: float = 1.0
    position: str = "bottom"


@app.post("/api/jobs/{jid}/export")
def export(jid: str, body: ExportIn):
    return jobs.export(jid, body.srt, body.burn, {"size": max(0.6, min(1.6, body.size)), "position": body.position})


# ---------------------------------------------------------------- memory

@app.get("/api/memory")
def get_memory():
    return memory.load()


class MemoryIn(BaseModel):
    kind: str                 # names | words | rules
    th: str = ""
    zh: str = ""
    text: str = ""
    note: str = ""


@app.post("/api/memory")
def add_memory(body: MemoryIn):
    if body.kind not in ("names", "words", "rules"):
        raise ValueError("Unknown kind.")
    return memory.add(body.kind, body.th, body.zh, body.text, body.note, source="added by hand")


class MemoryEditIn(BaseModel):
    th: str | None = None
    zh: str | None = None
    text: str | None = None
    note: str | None = None


@app.patch("/api/memory/{kind}/{eid}")
def edit_memory(kind: str, eid: str, body: MemoryEditIn):
    return memory.edit(kind, eid, body.model_dump(exclude_none=True))


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


app.mount("/", StaticFiles(directory=paths.WEB, html=True), name="web")


def _already_running(url):
    import urllib.request
    try:
        with urllib.request.urlopen(url + "api/status", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def main():
    import uvicorn
    paths.ensure_dirs()
    url = f"http://127.0.0.1:{PORT}/"
    if _already_running(url):
        print(f"AutoCaption is already running at {url}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"AutoCaption is running at {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
