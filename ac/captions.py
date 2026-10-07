"""Caption lines: cut Whisper's output into readable lines, and write SRT / ASS files.

A line (cue) is {"id", "start", "end", "th", "zh", "conf", "kind", "flag", "note", "status"}.
  conf    0..1, how sure Whisper was of the words (lowest-confidence words weigh most)
  kind    "speech" | "song" (sung lyrics) | "sound" (laughing, music only)
  flag    None, or what you (or the self-check) said is wrong: "heard" | "translation" | "timing" | "other"
  status  "auto" | "fixed" (changed after feedback) | "edited" (you typed it)
"""
import math
import re

MAX_CHARS = 34       # Thai letters per line (marks above/below don't count)
MAX_SECONDS = 5.5
GAP_SPLIT = 0.45     # a pause this long starts a new line
MIN_SECONDS = 0.9

_THAI_MARK = re.compile(r"[ัิ-ฺ็-๎]")


def visible_len(text):
    return len(_THAI_MARK.sub("", text))


def _segment_conf(seg):
    probs = [w["p"] for w in seg.get("words") or [] if w["word"].strip()]
    if not probs:
        return round(math.exp(min(0, seg.get("avg_logprob", -1))), 3)
    probs.sort()
    low = probs[: max(1, len(probs) // 4)]          # the worst quarter of the words
    return round(0.5 * sum(low) / len(low) + 0.5 * sum(probs) / len(probs), 3)


def _word_starts(words):
    """Which of Whisper's pieces start a real Thai word. Whisper's pieces are sub-word
    tokens, so a line may only break where the Thai word splitter agrees."""
    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        return [True] * len(words)
    text = "".join(w["word"] for w in words)
    bounds, pos = {0, len(text)}, 0
    for tok in word_tokenize(text, engine="newmm", keep_whitespace=True):
        pos += len(tok)
        bounds.add(pos)
    out, pos = [], 0
    for w in words:
        out.append(pos in bounds or w["word"][:1] in " \t" or not _THAI.search(w["word"][:1]))
        pos += len(w["word"])
    return out


_THAI = re.compile(r"[฀-๿]")


def from_segments(segments, first_id=1):
    """Whisper segments -> caption lines, split at pauses, spaces and length limits,
    never inside a Thai word."""
    lines = []
    for seg in segments:
        words = [w for w in seg.get("words") or [] if w["word"]]
        if not any(w["word"].strip() for w in words):
            lines.append(_line(seg["start"], seg["end"], seg["text"], _segment_conf(seg)))
            continue
        starts = _word_starts(words)
        cur = []
        for w, ok in zip(words, starts):
            if cur and ok:
                text = "".join(x["word"] for x in cur).strip()
                gap = w["start"] - cur[-1]["end"]
                long_ = visible_len(text + w["word"]) > MAX_CHARS or w["end"] - cur[0]["start"] > MAX_SECONDS
                # Thai puts a space between phrases: a good place to break once the line has some length
                at_space = w["word"].startswith(" ") and visible_len(text) > MAX_CHARS * 0.55
                if gap >= GAP_SPLIT or long_ or at_space:
                    lines.append(_from_words(cur))
                    cur = []
            cur.append(w)
        if cur:
            lines.append(_from_words(cur))
    lines = [l for l in lines if l["th"]]
    # tiny leftovers join the line before when they follow straight on
    merged = []
    for l in lines:
        if merged and visible_len(l["th"]) <= 3 and l["start"] - merged[-1]["end"] < 0.3 \
                and visible_len(merged[-1]["th"]) + visible_len(l["th"]) <= MAX_CHARS + 6:
            p = merged[-1]
            p["th"] = (p["th"] + l["th"]).strip()
            p["end"] = l["end"]
            p["conf"] = min(p["conf"], l["conf"])
        else:
            merged.append(l)
    for i, l in enumerate(merged):
        l["id"] = first_id + i
    return fix_timing(merged)


def _from_words(words):
    probs = sorted(w["p"] for w in words)
    low = probs[: max(1, len(probs) // 3)]
    conf = round(0.5 * sum(low) / len(low) + 0.5 * sum(probs) / len(probs), 3)
    return _line(words[0]["start"], words[-1]["end"], "".join(w["word"] for w in words).strip(), conf)


def _line(start, end, th, conf):
    return {"id": 0, "start": round(start, 3), "end": round(end, 3), "th": th.strip(), "zh": "",
            "conf": conf, "kind": "speech", "flag": None, "note": "", "status": "auto"}


def fix_timing(lines):
    """Short lines stay up long enough to read, without running into the next one."""
    lines.sort(key=lambda l: l["start"])
    for i, l in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else l["end"] + 10
        want = max(l["end"], l["start"] + MIN_SECONDS, l["start"] + 0.06 * visible_len(l["th"]))
        l["end"] = round(min(want + 0.15, max(l["end"], nxt - 0.04)), 3)
        if l["end"] <= l["start"]:
            l["end"] = round(l["start"] + 0.3, 3)
    return lines


# ---------------------------------------------------------------- files

def _ts(t, sep=","):
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def srt(lines, which):
    """which: "th" | "zh" | "both" (Chinese on top, Thai under it)."""
    out, n = [], 0
    for l in lines:
        th, zh = l["th"].strip(), (l.get("zh") or "").strip()
        text = {"th": th, "zh": zh, "both": "\n".join(x for x in (zh, th) if x)}[which]
        if not text:
            continue
        n += 1
        out.append(f"{n}\n{_ts(l['start'])} --> {_ts(l['end'])}\n{text}\n")
    return "\n".join(out)


def parse_srt(text):
    """Someone's SRT (or a CapCut export) -> [{"start", "end", "text"}]."""
    items = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = block[m.end():].strip()
        items.append({"start": start, "end": end, "text": re.sub(r"<[^>]+>", "", body)})
    return items


def looks_like_srt(text):
    return bool(re.search(r"\d+:\d+:\d+[,.]\d+\s*-->", text or ""))
