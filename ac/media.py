"""ffmpeg helpers: probe, audio for listening, a browser-playable copy, burning captions in."""
import json
import re
import subprocess
from pathlib import Path

from . import paths


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
    return {
        "duration": float(d.get("format", {}).get("duration") or 0),
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
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


def burn(src, ass_file, dst, duration, on_progress):
    """Draw the captions into the picture (needs ffmpeg with libass: brew install ffmpeg-full)."""
    if "subtitles" not in subprocess.run([paths.ffmpeg(), "-hide_banner", "-filters"],
                                         capture_output=True, text=True).stdout:
        raise MediaError("Burning captions in needs the full ffmpeg. In Terminal run: brew install ffmpeg-full")
    ass = str(ass_file).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
            "-i", str(src), "-vf", f"subtitles='{ass}'",
            "-c:v", "h264_videotoolbox", "-q:v", "65", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(dst)]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        m = re.match(r"out_time_us=(\d+)", line)
        if m and duration:
            on_progress(min(1.0, int(m.group(1)) / 1e6 / duration))
    err = p.stderr.read()
    if p.wait() != 0:
        raise MediaError("Burning the captions failed: " + err.strip()[-300:])
