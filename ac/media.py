"""ffmpeg helpers: probe, audio for listening, a browser-playable copy, burning captions in."""
import json
import re
import subprocess
from pathlib import Path

from . import paths, procs


class MediaError(RuntimeError):
    pass


def probe(path):
    p = subprocess.run([paths.ffprobe(), "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)], capture_output=True, text=True)
    if p.returncode != 0:
        raise MediaError("That file isn't a video ffmpeg can read.")
    d = json.loads(p.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not a:
        raise MediaError("That video has no sound to caption.")
    w, h = (int(v["width"]), int(v["height"])) if v else (0, 0)
    rot = 0
    for sd in (v or {}).get("side_data_list") or []:
        rot = int(sd.get("rotation") or rot)
    rot = rot or int(((v or {}).get("tags") or {}).get("rotate") or 0)
    if abs(rot) % 180 == 90:                 # phone videos filmed upright: ffmpeg turns them, so do we
        w, h = h, w
    return {
        "duration": float(d.get("format", {}).get("duration") or 0),
        "width": w,
        "height": h,
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name"),
        "container": d.get("format", {}).get("format_name", ""),
    }


def _run(args, what):
    p = subprocess.run([paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise MediaError(f"{what} failed: {p.stderr.strip()[-300:]}")


def extract_audio(src, dst, start=None, end=None, rate=16000):
    """Mono 16 kHz WAV, what Whisper listens to."""
    cut = []
    if start is not None:
        cut += ["-ss", f"{max(0, start):.3f}"]
    if end is not None:
        cut += ["-to", f"{end:.3f}"]
    _run([*cut, "-i", str(src), "-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)],
         "Reading the sound")


def cut_wav(src_wav, dst, start, end):
    _run(["-ss", f"{max(0, start):.3f}", "-to", f"{end:.3f}", "-i", str(src_wav), "-c", "copy", str(dst)],
         "Cutting the clip")


def browser_copy(src, info, dst):
    """The page plays the video next to the captions. H.264/HEVC + AAC in MP4/MOV plays
    everywhere (Safari too); anything else gets a quick 720p H.264 copy."""
    playable = (info["vcodec"] in ("h264", "hevc") and info["acodec"] in ("aac", "mp3")
                and any(c in info["container"] for c in ("mp4", "mov")))
    if playable:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(Path(src).name)
        return
    _run(["-i", str(src), "-vf", "scale=-2:'min(720,ih)'", "-c:v", "h264_videotoolbox", "-b:v", "3M",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)], "Making a playable copy")


def burn(src, frames_list, dst, duration, on_progress):
    """Lay the rendered caption frames (style.frames) over the video."""
    args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
            "-i", str(src), "-f", "concat", "-safe", "0", "-i", str(frames_list),
            "-filter_complex", "[1:v]format=rgba[c];[0:v][c]overlay=eof_action=pass:format=auto,format=yuv420p[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "h264_videotoolbox", "-q:v", "65", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(dst)]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    procs.register(p)
    for line in p.stdout:
        m = re.match(r"out_time_us=(\d+)", line)
        if m and duration:
            on_progress(min(1.0, int(m.group(1)) / 1e6 / duration))
    err = p.stderr.read()
    code = p.wait()
    procs.unregister(p)
    procs.check()
    if code != 0:
        raise MediaError("Burning the captions failed: " + err.strip()[-300:])


def contact_sheets(src, folder, every):
    """Small frames every `every` seconds, 4×4 to a sheet, each labelled with its time, so Claude can see the video."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _run(["-i", str(src), "-vf", f"fps=1/{every},scale=320:-2,drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=16:"
          f"fontcolor=yellow:box=1:boxcolor=black@0.7,tile=4x4", "-fps_mode", "vfr", str(folder / "sheet_%03d.jpg")],
         "Making contact sheets")
    return sorted(folder.glob("sheet_*.jpg"))
