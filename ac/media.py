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


def burn(src, frames_list, dst, duration, on_progress, sprites=(), vertical=None, start=0.0):
    """Lay the rendered caption frames (style.frames) over the video, then any moving items
    (style.sprites): each a still picture that ffmpeg moves/turns/squashes on every frame.
    vertical: a style.vertical_plan: the picture goes on a 9:16 canvas first (cropped, or on a blurred copy).
    start: save from this moment (a part of the video); the frames and sprites are timed from it."""
    inputs = [*(["-ss", f"{start:.3f}"] if start else []), "-i", str(src), "-f", "concat", "-safe", "0", "-i", str(frames_list)]
    graph = ["[1:v]format=rgba[c]"]
    if vertical:
        W, H = vertical["w"], vertical["h"]
        x, y, pw, ph = vertical["pic"]
        if vertical["fit"] == "fill":
            graph.append(f"[0:v]scale={pw}:{ph},crop={W}:{H}:{-x}:{-y},setsar=1[base]")
        else:
            graph.append(f"[0:v]split[bga][fga];[bga]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                         f"gblur=sigma=40,eq=brightness=-0.12[bg];[fga]scale={pw}:{ph}[fg];[bg][fg]overlay={x}:{y},setsar=1[base]")
        graph.append("[base][c]overlay=eof_action=pass:format=auto[v0]")
    else:
        graph.append("[0:v][c]overlay=eof_action=pass:format=auto[v0]")
    for i, sp in enumerate(sprites):
        inputs += ["-loop", "1", "-framerate", "30", "-i", sp["png"]]
        pre = "format=rgba" + ("," + sp["pre"] if sp["pre"] else "")
        graph.append(f"[{i + 2}:v]{pre}[s{i}]")
        graph.append(f"[v{i}][s{i}]overlay=x='{sp['x']}':y='{sp['y']}':eval=frame:format=auto:shortest=0:"
                     f"enable='between(t,{sp['start']:.3f},{sp['end']:.3f})'[v{i + 1}]")
    graph.append(f"[v{len(sprites)}]format=yuv420p[v]")
    args = [paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
            *inputs, "-filter_complex", ";".join(graph), "-t", f"{duration:.3f}" if duration else "36000",
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


def join(clips, dst):
    """Videos saved the same way, one after the other (no re-encoding)."""
    lst = Path(dst).with_suffix(".join.txt")
    lst.write_text("".join(f"file '{c}'\n" for c in clips))          # the job's own folder: no quotes in these paths
    try:
        _run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(dst)], "Joining the parts")
    finally:
        lst.unlink(missing_ok=True)


def contact_sheets(src, folder, every):
    """Small frames every `every` seconds, 4×4 to a sheet, each labelled with its time, so Claude can see the video."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _run(["-i", str(src), "-vf", f"fps=1/{every},scale=320:-2,drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=16:"
          f"fontcolor=yellow:box=1:boxcolor=black@0.7,tile=4x4", "-fps_mode", "vfr", str(folder / "sheet_%03d.jpg")],
         "Making contact sheets")
    return sorted(folder.glob("sheet_*.jpg"))
