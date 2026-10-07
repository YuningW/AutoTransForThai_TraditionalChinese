"""Speech to text with Whisper on the Mac's GPU (MLX).

A voice detector (Silero VAD) finds where people talk first, and Whisper only listens
to those parts, a few seconds at a time. Over music or silence Whisper otherwise makes
lines up ("ฮ. ฮ. ฮ.", the same phrase forty times) and burns minutes retrying them.

Runs as its own process so the model's memory is handed back when it finishes:
    python -m ac.listen <audio.wav> <out.json> [hint text] [temperature] [novad]
Prints {"progress": 0..1} lines while working, then {"done": n_segments}.
"""
import json
import re
import sys
import warnings
import wave

import numpy as np

from . import paths

SR = 16000
MAX_CHUNK = 28.0     # Whisper hears 30 s at a time
JOIN_GAP = 1.2       # speech parts closer than this are listened to together
# when one model drops a stretch of talking, the other gets a try
OTHER_MODEL = {"mlx-community/whisper-large-v3-mlx": "mlx-community/whisper-large-v3-turbo",
               "mlx-community/whisper-large-v3-turbo": "mlx-community/whisper-large-v3-mlx"}


def say(**msg):
    print(json.dumps(msg, ensure_ascii=False), flush=True)


def load_wav(path):
    with wave.open(str(path)) as w:
        if w.getframerate() != SR or w.getnchannels() != 1:
            raise RuntimeError("listen.py wants 16 kHz mono audio")
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def speech_parts(audio):
    """[(start, end)] in seconds where someone seems to be talking, grouped into chunks."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    ts = get_speech_timestamps(torch.from_numpy(audio), load_silero_vad(), sampling_rate=SR,
                               return_seconds=True, min_silence_duration_ms=350, speech_pad_ms=250)
    chunks = []
    for t in ts:
        s, e = float(t["start"]), float(t["end"])
        while e - s > MAX_CHUNK:            # one long stretch of talking: cut it
            chunks.append([s, s + MAX_CHUNK])
            s += MAX_CHUNK
        if chunks and s - chunks[-1][1] < JOIN_GAP and e - chunks[-1][0] <= MAX_CHUNK:
            chunks[-1][1] = e
        else:
            chunks.append([s, e])
    return chunks


def _junk(seg, text):
    """Whisper's made-up lines: loops, a lone letter, or confident words over no speech."""
    if seg.get("compression_ratio", 0) > 2.6:
        return True
    if re.fullmatch(r"(?:\s*\S{1,2}[.\s]*)", text) and seg.get("avg_logprob", 0) < -0.5:
        return True
    if seg.get("no_speech_prob", 0) > 0.75 and seg.get("avg_logprob", 0) < -0.7:
        return True
    return False


def _decode(piece, offset, end, model, hint, temps, language="th"):
    import mlx_whisper
    r = mlx_whisper.transcribe(piece, path_or_hf_repo=model, language=language, task="transcribe",
                               word_timestamps=True, verbose=None, temperature=temps,
                               condition_on_previous_text=False, initial_prompt=hint or None)
    out = []
    for seg in r.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text or _junk(seg, text):
            continue
        if out and out[-1]["text"] == text and seg["start"] + offset - out[-1]["end"] < 2:
            continue                      # the same words twice in a row
        out.append({
            "start": round(seg["start"] + offset, 3), "end": round(min(seg["end"] + offset, end + 0.3), 3), "text": text,
            "avg_logprob": round(seg.get("avg_logprob", 0), 3),
            "no_speech_prob": round(seg.get("no_speech_prob", 0), 3),
            "compression_ratio": round(seg.get("compression_ratio", 0), 2),
            "words": [{"start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3),
                       "word": w["word"], "p": round(w.get("probability", 0), 3)}
                      for w in seg.get("words") or []],
        })
    return out


def _coverage(segs, length):
    return sum(s["end"] - s["start"] for s in segs) / max(length, 0.1)


def transcribe(wav, hint="", temperature=None, vad=True):
    audio = load_wav(wav)
    total = len(audio) / SR
    parts = speech_parts(audio) if vad else [[0.0, total]]
    temps = (0.0, 0.4) if temperature is None else (temperature, min(1.0, temperature + 0.3))
    other = OTHER_MODEL.get(paths.WHISPER, "mlx-community/whisper-large-v3-mlx")
    out, done = [], 0.0
    work = sum(e - s for s, e in parts) or 1
    for s, e in parts:
        piece = audio[int(s * SR):int(min(total, e) * SR)]
        if len(piece) < SR * 0.3:
            continue
        segs = _decode(piece, s, e, paths.WHISPER, hint, temps)
        # The voice detector heard talking but almost nothing came back: Whisper sometimes
        # drops a whole stretch, and told "this is Thai" it often drops English entirely.
        # Listen again: letting it pick the language, more loosely, then with the other model.
        if e - s > 2.5 and _coverage(segs, e - s) < 0.3:
            for model, t, lang in ((paths.WHISPER, (0.0, 0.4), None), (paths.WHISPER, (0.3, 0.6), "th"),
                                   (other, (0.0, 0.4), None)):
                if not model:
                    continue
                again = _decode(piece, s, e, model, hint, t, lang)
                if _coverage(again, e - s) > _coverage(segs, e - s) + 0.15:
                    segs = again
                if _coverage(segs, e - s) >= 0.3:
                    break
        if out and segs and segs[0]["text"] == out[-1]["text"]:
            segs = segs[1:]
        out += segs
        done += e - s
        say(progress=round(min(1.0, done / work), 3))
    return out


def main():
    warnings.filterwarnings("ignore")
    wav, out = sys.argv[1], sys.argv[2]
    hint = sys.argv[3] if len(sys.argv) > 3 else ""
    temp = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
    vad = not (len(sys.argv) > 5 and sys.argv[5] == "novad")
    try:
        segs = transcribe(wav, hint, temp, vad)
        with open(out, "w") as f:
            json.dump(segs, f, ensure_ascii=False)
        say(done=len(segs))
    except Exception as e:  # reported to the page, not a traceback
        say(error=str(e) or e.__class__.__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
