"""Take music and crowd noise away so only the voices are left (Demucs, as in VidToAudio).

Runs as its own process: python -m ac.voice <video> <voice16k.wav>
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


def main():
    warnings.filterwarnings("ignore")
    try:
        isolate(sys.argv[1], sys.argv[2])
        say(done=True)
    except Exception as e:
        say(error=str(e) or e.__class__.__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
