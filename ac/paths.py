"""Where things live on disk."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
# Everything the tool makes while working stays out of git (see .gitignore).
WORK = Path(os.environ.get("AC_WORK", ROOT / "work"))
JOBS = WORK / "jobs"
# What the tool has learned from your feedback: names, words, style rules.
MEMORY = WORK / "memory.json"
# Finished SRT files and captioned videos.
OUT = Path(os.environ.get("AC_OUT", Path.home() / "Movies" / "AutoCaption"))
# Voice-isolation models: shared with VidToAudio so htdemucs isn't downloaded twice.
SEP_MODELS = Path(os.environ.get("AC_SEP_MODELS", Path.home() / "Library/Caches/VidToAudio/models"))

WHISPER = os.environ.get("AC_WHISPER", "mlx-community/whisper-large-v3-mlx")
# "Quicker listening": about 6x faster, a bit less accurate on Thai
WHISPER_FAST = "mlx-community/whisper-large-v3-turbo"
CLAUDE_MODEL = os.environ.get("AC_CLAUDE_MODEL", "claude-opus-5-5")


def ffmpeg():
    """The full Homebrew build has libass (needed to burn captions in); plain ffmpeg is fine for the rest."""
    full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
    return str(full) if full.exists() else (shutil.which("ffmpeg") or "ffmpeg")


def ffprobe():
    full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffprobe")
    return str(full) if full.exists() else (shutil.which("ffprobe") or "ffprobe")


def claude():
    for p in (shutil.which("claude"), Path.home() / ".local/bin/claude", "/opt/homebrew/bin/claude"):
        if p and Path(p).exists():
            return str(p)
    return None


def ensure_dirs():
    for d in (JOBS, OUT, SEP_MODELS):
        d.mkdir(parents=True, exist_ok=True)
