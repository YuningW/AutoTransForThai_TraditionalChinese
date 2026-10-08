"""Speech to text with Whisper on the Mac's GPU (MLX).

A voice detector (Silero VAD) finds where people talk first, and Whisper only listens
to those parts, a few seconds at a time. Over music or silence Whisper otherwise makes
lines up ("ฮ. ฮ. ฮ.", the same phrase forty times) and burns minutes retrying them.

Runs as its own process so the model's memory is handed back when it finishes:
    python -m ac.listen <audio.wav> <out.json> [hint text] [temperature] [novad]
Prints {"progress": 0..1} lines while working, then {"done": n_segments}.
"""
import json
import os
import re
import sys
import warnings
import wave

import numpy as np

from . import paths

SR = 16000
TOKENS_PER_SECOND = 15
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


def speech_parts(audio, join_gap=JOIN_GAP, min_silence=350, max_chunk=MAX_CHUNK, gaps=None):
    """[(start, end)] in seconds where someone seems to be talking, grouped into chunks.
    join_gap 0 keeps every pause as a boundary (see SPLIT_AT_PAUSES). gaps (a list), if given,
    collects the middle of every pause that was joined over: good places to cut a line later."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    ts = get_speech_timestamps(torch.from_numpy(audio), load_silero_vad(), sampling_rate=SR,
                               return_seconds=True, min_silence_duration_ms=min_silence, speech_pad_ms=150 if min_silence < 300 else 250)
    chunks = []
    for t in ts:
        s, e = float(t["start"]), float(t["end"])
        while e - s > MAX_CHUNK:            # one long stretch of talking: cut it
            chunks.append([s, s + MAX_CHUNK])
            s += MAX_CHUNK
        if chunks and s - chunks[-1][1] < join_gap and e - chunks[-1][0] <= max_chunk:
            if gaps is not None:
                gaps.append(round((chunks[-1][1] + s) / 2, 2))
            chunks[-1][1] = e
        else:
            chunks.append([s, e])
    return chunks


# The same bit (1-12 letters, with or without spaces) four or more times in a row: "อ่ะ อ่ะ อ่ะ อ่ะ", "คือคือคือคือ"
_LOOP = re.compile(r"(.{1,12}?)\s*(?:\1\s*){3,}")
# Thai in UTF-8 compresses about 3:1 even when it's ordinary speech, so Whisper's usual
# "compresses too well = stuck in a loop" test (2.4) throws away good Thai lines. Real loops score 10+.
THAI_COMPRESSION_LIMIT = 6.0


def _junk(seg, text):
    """Whisper's made-up lines: loops, a lone letter, or confident words over no speech."""
    if seg.get("compression_ratio", 0) > THAI_COMPRESSION_LIMIT:
        return True
    loop = _LOOP.search(text)
    if loop and len(loop.group(0)) >= max(8, 0.5 * len(text)):
        return True
    if re.fullmatch(r"(?:\s*\S{1,2}[.\s]*)", text) and seg.get("avg_logprob", 0) < -0.5:
        return True
    if seg.get("no_speech_prob", 0) > 0.75 and seg.get("avg_logprob", 0) < -0.7:
        return True
    return False


def _decode(piece, offset, end, model, hint, temps, language="th"):
    import mlx_whisper
    # A stuck model repeats itself until the token limit (224), then retries: on a 3-second piece that is
    # minutes of wasted work. Nobody says more than ~15 tokens a second, so cap it by the piece's length.
    sample_len = min(224, int(len(piece) / SR * TOKENS_PER_SECOND) + 24)
    r = mlx_whisper.transcribe(piece, path_or_hf_repo=model, language=language, task="transcribe",
                               word_timestamps=os.environ.get("AC_WORD_TIMES", "1") == "1", verbose=None, temperature=temps,
                               condition_on_previous_text=False, initial_prompt=hint or None,
                               sample_len=sample_len, compression_ratio_threshold=THAI_COMPRESSION_LIMIT)
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
    # Thai-tuned models write a whole chunk as one run of text with no usable timing inside, so
    # lines could only be cut by length (mid-sentence, two speakers in one line). For them each
    # stretch between pauses is listened to on its own: a change of speaker nearly always has a pause.
    split = os.environ.get("AC_SPLIT_AT_PAUSES") == "1"
    # Pieces of up to 12 s, joined across pauses under 0.8 s: on a Thai interview this was twice as fast
    # as one piece per pause with the same accuracy (each piece costs a full pass however short it is).
    # Claude still cuts lines where the speaker changes.
    gap, longest = (float(os.environ.get("AC_SPLIT_JOIN", "0.8")), float(os.environ.get("AC_SPLIT_MAX", "12"))) \
        if split else (JOIN_GAP, MAX_CHUNK)
    pauses = []
    parts = speech_parts(audio, gap, max_chunk=longest, gaps=pauses) if vad else [[0.0, total]]
    temps = (0.0, 0.4) if temperature is None else (temperature, min(1.0, temperature + 0.3))
    other = OTHER_MODEL.get(paths.WHISPER, "mlx-community/whisper-large-v3-mlx")
    pieces = [(s, e, audio[int(s * SR):int(min(total, e) * SR)]) for s, e in parts]
    pieces = [x for x in pieces if len(x[2]) >= SR * 0.3]
    work = sum(e - s for s, e, _ in pieces) or 1
    found, done = {}, 0.0
    for i, (s, e, piece) in enumerate(pieces):
        found[i] = _decode(piece, s, e, paths.WHISPER, hint, temps)
        done += e - s
        say(progress=round(0.9 * min(1.0, done / work), 3))
    # The voice detector heard talking but almost nothing came back: Whisper sometimes drops a
    # whole stretch, and told "this is Thai" it often drops English entirely. Listen again, letting
    # it pick the language, more loosely, then with the other model. Each try runs over all such
    # stretches in one go, because switching models means loading 3 GB again.
    for model, t, lang in ((paths.WHISPER, (0.0, 0.4), None), (paths.WHISPER, (0.3, 0.6), "th"), (other, (0.0, 0.4), None)):
        weak = [i for i, (s, e, _) in enumerate(pieces) if e - s > 2.5 and _coverage(found[i], e - s) < 0.3]
        if not weak or not model:
            continue
        for i in weak:
            s, e, piece = pieces[i]
            again = _decode(piece, s, e, model, hint, t, lang)
            if _coverage(again, e - s) > _coverage(found[i], e - s) + 0.15:
                found[i] = again
    say(progress=1.0)
    out = []
    for i in range(len(pieces)):
        segs = found[i]
        s, e, _ = pieces[i]
        inside = [g for g in pauses if s < g < e]
        for seg in segs:                       # pauses inside this piece: where its text can be cut
            seg["gaps"] = [g for g in inside if seg["start"] < g < seg["end"]] or inside
        if out and segs and segs[0]["text"] == out[-1]["text"]:
            segs = segs[1:]
        out += segs
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
