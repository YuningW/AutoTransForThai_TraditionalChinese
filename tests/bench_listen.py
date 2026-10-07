"""Compare listening models against subtitles you trust.

    .venv/bin/python tests/bench_listen.py <audio.wav> <reference.json> <model_key> [<model_key> ...]

reference.json: [{"start", "end", "th"}] (for example a video's own burned-in Thai subtitles).
For each reference line it looks for the best match in what the model heard within a few
seconds of it. "found" = how much of the reference text it got (character level, 0-100);
"missed" = reference lines it got less than half of (skipped or badly misheard).
"""
import json
import os
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ac import models  # noqa: E402


def norm(s):
    return re.sub(r"[\s\.,!?'\"…\-]+", "", s.lower())


def best_match(ref, hyp):
    """How much of ref appears in hyp (0..1), allowing hyp to be longer."""
    if not ref:
        return 1.0
    if not hyp:
        return 0.0
    m = SequenceMatcher(None, ref, hyp, autojunk=False)
    return sum(b.size for b in m.get_matching_blocks()) / len(ref)


def score(segments, reference, slack=3.0):
    found, missed = [], []
    for r in reference:
        near = "".join(s["text"] for s in segments if s["end"] >= r["start"] - slack and s["start"] <= r["end"] + 1 + slack)
        f = best_match(norm(r["th"]), norm(near))
        found.append(f)
        if f < 0.5:
            missed.append(r)
    return 100 * sum(found) / len(found), missed


def main():
    wav, ref = sys.argv[1], json.loads(Path(sys.argv[2]).read_text())
    out_dir = Path(sys.argv[2]).parent
    for key in sys.argv[3:]:
        path = models.mlx_path(key)
        out = out_dir / f"bench_{key}.json"
        t = time.time()
        p = subprocess.run([sys.executable, "-m", "ac.listen", wav, str(out)], cwd=ROOT,
                           env={**os.environ, "AC_WHISPER": path}, capture_output=True, text=True)
        secs = time.time() - t
        if p.returncode != 0:
            print(f"{key:22} failed: {p.stdout[-300:]}")
            continue
        segs = json.loads(out.read_text())
        found, missed = score(segs, ref)
        print(f"{key:22} found {found:5.1f}%   missed {len(missed):3d}/{len(ref)}   {secs:5.0f} s", flush=True)
        for m in missed[:6]:
            print(f"{'':24}missed {m['start']:>4}s  {m['th']}")


if __name__ == "__main__":
    main()
