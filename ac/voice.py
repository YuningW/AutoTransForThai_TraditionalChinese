"""Take music and crowd noise away so only the voices are left (Demucs, as in VidToAudio).

Runs as its own process: python -m ac.voice <video> <voice16k.wav>
                          python -m ac.voice --keep <video> <out.wav> <start> <end>   (for saving: full quality, just a stretch)
Prints {"done": true} or {"error": ...}.
"""
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from . import media, paths


def say(**msg):
    print(json.dumps(msg), flush=True)


def isolate(src, dst):
    from audio_separator.separator import Separator
    dst = Path(dst)
    tmp = Path(tempfile.mkdtemp(prefix="voice-", dir=dst.parent))
    try:
        full = tmp / "full.wav"
        subprocess.run([paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-vn", "-ac", "2", "-ar", "44100", str(full)], check=True)
        sep = Separator(log_level=logging.ERROR, model_file_dir=str(paths.SEP_MODELS),
                        output_dir=str(tmp), output_format="WAV")
        sep.load_model("htdemucs.yaml")
        sep.separate(str(full), custom_output_names={"Vocals": "vocals", "Drums": "d", "Bass": "b", "Other": "o"})
        media.extract_audio(tmp / "vocals.wav", dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


KEEP_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"   # the cleanest voices of those tried (BS-Roformer)


def keep_voices(src, dst, start, end):
    """The voices of start..end, music taken out, at full quality (44.1 kHz stereo) for a saved video."""
    from audio_separator.separator import Separator
    dst = Path(dst)
    tmp = Path(tempfile.mkdtemp(prefix="keep-", dir=dst.parent))
    try:
        full = tmp / "full.wav"
        subprocess.run([paths.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                        "-i", str(src), "-vn", "-ac", "2", "-ar", "44100", str(full)], check=True)
        sep = Separator(log_level=logging.ERROR, model_file_dir=str(paths.SEP_MODELS), output_dir=str(tmp), output_format="WAV")
        sep.load_model(KEEP_MODEL)
        out = sep.separate(str(full))
        vocals = next(tmp / f for f in out if "vocal" in f.lower())
        shutil.move(str(vocals), str(dst))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    warnings.filterwarnings("ignore")
    try:
        if sys.argv[1] == "--keep":
            keep_voices(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]))
            say(done=True)
            return
        isolate(sys.argv[1], sys.argv[2])
        say(done=True)
    except Exception as e:
        say(error=str(e) or e.__class__.__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
