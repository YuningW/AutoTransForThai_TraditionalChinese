"""Who is talking, by voice: a speaker-recognition model (SpeechBrain ECAPA) turns each line's
audio into a voiceprint. Lines you assigned teach it each person's voice; the rest are matched
to the closest person when the match is clear. Runs on the Mac, no Claude tokens.

On a 21-minute, six-person interview with named English captions, after 5 lines per person:
93% of lines matched the right person (Milk vs Love: 99%). With the cut-offs below it colours
about 70% of lines with under 3% wrong, and leaves the unclear ones for you.

As its own process (the model's memory is handed back when it finishes):
    python -m ac.voices <audio.wav> <request.json> <out.npz>
request: [{"key", "start", "end"}]  ->  out: one 192-number voiceprint per key.
"""
import json
import sys
import warnings
import wave

import numpy as np

from . import models

SR = 16000
MIN_SECONDS = 0.6        # shorter lines don't carry enough voice
MIN_SIMILARITY = 0.30    # how close to a person's voice a line must be
MIN_MARGIN = 0.10        # ...and how much closer than to the next person
MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def say(**msg):
    print(json.dumps(msg), flush=True)


def embed(wav, items):
    from speechbrain.inference.speaker import EncoderClassifier
    import torch
    m = EncoderClassifier.from_hparams(source=MODEL, savedir=str(models.CACHE / "ecapa"), run_opts={"device": "cpu"})
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    out = {}
    for i, it in enumerate(items):
        seg = x[int(max(0, it["start"] - 0.05) * SR):int((it["end"] + 0.05) * SR)]
        if len(seg) < SR * 0.3:
            continue
        with torch.no_grad():
            e = m.encode_batch(torch.from_numpy(seg)[None]).squeeze().numpy()
        out[it["key"]] = (e / (np.linalg.norm(e) + 1e-9)).astype(np.float32)
        if i % 20 == 0:
            say(progress=round(i / max(1, len(items)), 3))
    return out


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def match(vec, prints):
    """prints: {person_id: unit voiceprint}. The person, or None when it isn't clear."""
    if not prints:
        return None
    sims = sorted(((float(vec @ p), pid) for pid, p in prints.items()), reverse=True)
    best, pid = sims[0]
    second = sims[1][0] if len(sims) > 1 else -1.0
    if best >= MIN_SIMILARITY and best - second >= MIN_MARGIN:
        return pid
    return None


def main():
    warnings.filterwarnings("ignore")
    try:
        items = json.loads(open(sys.argv[2]).read())
        out = embed(sys.argv[1], items)
        np.savez(sys.argv[3], **out)
        say(done=len(out))
    except Exception as e:
        say(error=str(e) or e.__class__.__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
