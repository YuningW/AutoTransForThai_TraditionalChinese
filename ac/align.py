"""Exact timing for each caption line: forced alignment.

The Thai-tuned listening models say when a piece of speech (up to ~12 s) starts and ends, not when each word
inside it is said, so lines cut from one piece got times shared out by text length, which drifts by a second or
two. Here a Thai speech model (wav2vec2, CTC) reads each line's own letters against the sound and finds where
they are spoken: the line starts at its first letter and ends at its last. Lines that can't be matched (all
English, or the words don't fit the sound) keep the times they had.

    python -m ac.align <audio.wav> <lines.json> <out.json>     (run in its own process: torch + a 1.2 GB model)
"""
import json
import sys

MODEL = "airesearch/wav2vec2-large-xlsr-53-th"
SR = 16000
JOIN = 1.0          # lines closer than this are aligned together, in one window of sound
WINDOW = 30.0       # longest window, seconds
MARGIN = 0.8        # sound taken before and after a window: the old times may be off by about this much
MIN_SCORE = 0.35    # a line's letters must match the sound at least this well (average probability)
LEAD, TAIL = 0.08, 0.25   # a caption shows a little before the first letter and stays a little after the last


def groups(lines):
    """Runs of lines one after another (no overlap: two people at once are left as they are)."""
    out, cur = [], []
    for l in sorted(lines, key=lambda x: x["start"]):
        if cur and (l["start"] - cur[-1]["end"] > JOIN or l["end"] - cur[0]["start"] > WINDOW
                    or l["start"] < cur[-1]["end"] - 0.5):
            out.append(cur)
            cur = []
        cur.append(l)
    if cur:
        out.append(cur)
    return out


class Aligner:
    def __init__(self):
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        self.torch = torch
        self.proc = Wav2Vec2Processor.from_pretrained(MODEL)
        self.model = Wav2Vec2ForCTC.from_pretrained(MODEL).eval()
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model.to(self.device)
        self.vocab = self.proc.tokenizer.get_vocab()
        self.blank = self.proc.tokenizer.pad_token_id
        self.space = self.vocab.get("|")

    def tokens(self, text):
        ids, last_space = [], True
        for ch in text:
            if ch.isspace():
                if not last_space and self.space is not None:
                    ids.append(self.space)
                last_space = True
            elif ch in self.vocab:
                ids.append(self.vocab[ch])
                last_space = False
        while ids and ids[-1] == self.space:
            ids.pop()
        return ids

    def emissions(self, audio):
        torch = self.torch
        x = (audio - audio.mean()) / (audio.std() + 1e-7)
        with torch.inference_mode():
            logits = self.model(torch.tensor(x[None], dtype=torch.float32, device=self.device)).logits
        return torch.log_softmax(logits.float(), dim=-1).cpu()

    def align_group(self, audio, group):
        """{line id: (start, end)} for the lines in one group that match the sound."""
        import torchaudio.functional as F
        torch = self.torch
        a = max(0.0, group[0]["start"] - MARGIN)
        b = min(len(audio) / SR, group[-1]["end"] + MARGIN)
        clip = audio[int(a * SR):int(b * SR)]
        if len(clip) < SR // 2:
            return {}
        toks, spans = [], []
        for l in group:
            t = self.tokens(l.get("th") or "")
            if toks and t and self.space is not None:
                toks.append(self.space)
            spans.append((len(toks), len(toks) + len(t)) if t else None)
            toks += t
        if not toks:
            return {}
        em = self.emissions(clip)
        T = em.shape[1]
        if T < len(toks) + sum(1 for i in range(1, len(toks)) if toks[i] == toks[i - 1]):
            return {}                                        # more letters than the sound has room for
        ali, scores = F.forced_align(em, torch.tensor([toks], dtype=torch.int32), blank=self.blank)
        ali, scores = ali[0], scores[0].exp()
        sec = (b - a) / T
        pieces = F.merge_tokens(ali, scores, blank=self.blank)   # one per letter, in order
        out = {}
        for l, sp in zip(group, spans):
            if not sp:
                continue
            mine = pieces[sp[0]:sp[1]]
            mine = [p for p in mine if p.token != self.space]
            if not mine:
                continue
            score = sum(p.score for p in mine) / len(mine)
            if score < MIN_SCORE:
                continue
            out[l["id"]] = (round(a + mine[0].start * sec - LEAD, 3), round(a + mine[-1].end * sec + TAIL, 3), round(score, 2))
        return out


def align_lines(audio, lines, on_progress=None):
    """{line id: (start, end, score)} for every line that could be matched."""
    al = Aligner()
    gs = groups([l for l in lines if (l.get("th") or "").strip() and l.get("kind") != "sound"])
    out = {}
    for i, g in enumerate(gs):
        out.update(al.align_group(audio, g))
        if on_progress and i % 5 == 0:
            on_progress(i / max(1, len(gs)))
    return out


def main():
    from .listen import load_wav
    wav, src, dst = sys.argv[1:4]
    lines = json.load(open(src))
    audio = load_wav(wav)

    def progress(p):
        print(json.dumps({"progress": round(p, 3)}), flush=True)
    found = align_lines(audio, lines, progress)
    json.dump({str(k): v for k, v in found.items()}, open(dst, "w"))
    print(json.dumps({"done": len(found)}), flush=True)


if __name__ == "__main__":
    main()
