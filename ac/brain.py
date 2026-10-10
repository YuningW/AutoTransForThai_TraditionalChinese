"""Everything Claude does: read helper screenshots, tidy the Thai, translate, check its own
work, fix what you flagged, and turn your feedback into lessons it keeps.

Claude can't hear. Whisper (listen.py) does the hearing; Claude only ever sees text and
pictures, so it is told which words Whisper was unsure of and never asked to guess sound.

Calls go through the Claude Code CLI (`claude -p`), which uses your Claude subscription;
no API key needed.
"""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import memory, models, paths, procs

CHUNK = 90          # lines per request; long videos run several requests side by side


class BrainError(RuntimeError):
    pass


def ask(system, prompt, schema, cwd, images=(), effort=None, timeout=900):
    """One structured answer from Claude. A failed call is tried once more before giving up."""
    try:
        return _ask(system, prompt, schema, cwd, images, effort, timeout)
    except BrainError as e:
        if "signed in" in str(e) or "isn't installed" in str(e):
            raise
        procs.check()
        return _ask(system, prompt, schema, cwd, images, effort, timeout)


def _ask(system, prompt, schema, cwd, images, effort, timeout):
    exe = paths.claude()
    if not exe:
        raise BrainError("The Claude command-line tool isn't installed. Install Claude Code, then sign in once in Terminal with: claude")
    args = [exe, "-p", "--model", models.claude_model(), "--output-format", "json",
            "--system-prompt", system, "--json-schema", json.dumps(schema),
            "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands"]
    if images:
        args += ["--tools", "Read", "--allowedTools", "Read"]
        prompt += "\n\nPictures to read (open each with the Read tool):\n" + "\n".join(str(p) for p in images)
    else:
        args += ["--tools", ""]
    effort = models.claude_effort(effort)
    if effort:
        args += ["--effort", effort]
    env = {k: v for k, v in os.environ.items()
           if k not in ("ELECTRON_RUN_AS_NODE", "CLAUDECODE", "ANTHROPIC_API_KEY") and not k.startswith("VSCODE_")}
    procs.check()
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=str(cwd), env=env)
    procs.register(proc)
    try:
        stdout, stderr = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise BrainError("Claude took too long to answer. Try again.") from None
    finally:
        procs.unregister(proc)
    procs.check()                        # the Stop button ended it
    p = subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        msg = (p.stderr or p.stdout).strip()[-300:]
        if "login" in msg.lower() or "auth" in msg.lower():
            msg = "Claude isn't signed in. Open Terminal and run: claude  (then sign in)"
        raise BrainError(msg or "Claude didn't answer.") from None
    _note_usage(cwd, out)
    if out.get("is_error") or out.get("structured_output") is None:
        raise BrainError(str(out.get("result") or out.get("api_error_status") or "Claude couldn't finish.")[:300])
    return out["structured_output"]


def _note_usage(cwd, out):
    """Each answer says how many tokens it took: kept per video in usage.jsonl, with the step it was for."""
    u = out.get("usage") or {}
    if not u:
        return
    try:
        step = json.loads((Path(cwd) / "job.json").read_text()).get("state", "")
    except (OSError, ValueError):
        step = ""
    row = {"at": time.time(), "step": step, "model": models.claude_model(),
           "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
           "cache_write": u.get("cache_creation_input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
           "cost_usd": out.get("total_cost_usd") or 0}
    try:
        with open(Path(cwd) / "usage.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def usage(job_dir):
    """Totals for one video, overall and per step."""
    rows = []
    try:
        rows = [json.loads(x) for x in (Path(job_dir) / "usage.jsonl").read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        pass
    keys = ("input", "output", "cache_write", "cache_read", "cost_usd")
    total = {k: sum(r.get(k, 0) for r in rows) for k in keys}
    total["calls"] = len(rows)
    steps = {}
    for r in rows:
        st = steps.setdefault(r.get("step") or "other", {k: 0 for k in keys} | {"calls": 0})
        for k in keys:
            st[k] += r.get(k, 0)
        st["calls"] += 1
    return {"total": total, "steps": steps}


def _lines_text(lines, fields=("th",)):
    rows = []
    for l in lines:
        row = {"id": l["id"], "time": f"{l['start']:.1f}-{l['end']:.1f}"}
        for f in fields:
            row[f] = l.get(f, "")
        if "conf" in fields or l.get("conf", 1) < 0.6:
            row["unsure"] = l.get("conf", 1) < 0.6
        rows.append(row)
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


def _chunks(lines, n=CHUNK):
    """Even batches of at most n lines (91 lines -> 46 + 45, not 90 + 1)."""
    if not lines:
        return [[]]
    parts = -(-len(lines) // n)
    size = -(-len(lines) // parts)
    return [lines[i:i + size] for i in range(0, len(lines), size)]


def _parallel(fn, items):
    jid = getattr(procs.current, "jid", None)
    chosen = models.in_use()

    def run(item):                       # worker threads belong to the same job (for Stop), with its model/effort
        procs.current.jid = jid
        models.use(*chosen)
        return fn(item)
    with ThreadPoolExecutor(max_workers=3) as ex:
        return list(ex.map(run, items))


def _context(job):
    info = job.get("info") or {}
    bits = []
    if info.get("title"):
        bits.append(f"Video title: {info['title']}")
    if info.get("uploader"):
        bits.append(f"Channel: {info['uploader']}")
    if info.get("description"):
        bits.append(f"Video description (may name the people in it):\n{info['description'][:1200]}")
    if job.get("about"):
        bits.append(f"What you were told about this video: {job['about']}")
    return "\n".join(bits)


def _helpers_text(helpers, kind, start=None, end=None):
    """Reference text the user gave, cut to the time range when it has timestamps."""
    out = []
    for h in helpers:
        if h["kind"] != kind or not h.get("text"):
            continue
        items = h.get("items")
        if items and start is not None:
            near = [i for i in items if i["end"] >= start - 5 and i["start"] <= end + 5]
            if near:
                out.append(f"[{h['label']}]\n" + "\n".join(f"{i['start']:.1f}-{i['end']:.1f} {i['text']}" for i in near))
            continue
        out.append(f"[{h['label']}]\n{h['text'][:20000]}")
    return "\n\n".join(out)


def _meaning_text(helpers, start, end):
    """Translations of this stretch written by people (the video's English/Chinese captions, the user's
    reference): they show what was said, though not the Thai words."""
    return _helpers_text([h for h in helpers if h.get("items")], "translation", start, end)


def _refs_for(helpers, start, end):
    """Both kinds of reference for one stretch, as prompt blocks."""
    orig = _helpers_text([h for h in helpers if h.get("items")], "original", start, end)
    mean = _meaning_text(helpers, start, end)
    return [f"Subtitles written by people for this stretch (Thai, as said):\n{orig}" if orig else "",
            f"Subtitles written by people for this stretch (a translation: shows what was meant, not the Thai words):\n{mean}" if mean else ""]


# ---------------------------------------------------------------- helpers (pictures)

READ_SYSTEM = """You copy caption text out of screenshots exactly as written. The screenshots are usually \
CapCut's caption list, a video frame with burned-in captions, or a page of someone's transcript or \
translation. Keep the original language and spelling; don't translate, fix or summarise. Keep the order. \
If a timestamp is shown next to a line, copy it into start/end as seconds."""

READ_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["language", "lines"], "properties": {
    "language": {"type": "string", "description": "th, zh, en or other"},
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {
        "text": {"type": "string"}, "start": {"type": "number"}, "end": {"type": "number"}}}}}}


def read_pictures(job_dir, pictures):
    """Screenshots -> text lines (one request for all of a helper's pictures, in order)."""
    r = ask(READ_SYSTEM, "Copy out every caption line from these pictures, in order. If two pictures "
            "overlap (the same lines appear twice), list each line once.", READ_SCHEMA, job_dir, images=pictures)
    return r["language"], r["lines"]


# ---------------------------------------------------------------- tidy the Thai

POLISH_SYSTEM = """You tidy Thai captions that a speech recogniser (Whisper) produced from a video. You cannot \
hear the audio: change words only when you have a real reason. Good reasons:
- a reference transcript from the user (for example CapCut's captions) shows what was said;
- the user's saved names and words (memory) show the right spelling;
- the line is clearly a recognition error: the same phrase looping, a stock phrase hallucinated over \
silence or music (for example "ขอบคุณที่รับชม", "ซับไตเติ้ลโดย..."), English words written in Thai letters \
where the speaker said English, or a word that makes no sense where a similar-sounding word does.
Keep the speaker's own style: slang, particles (นะ, ค่ะ, ครับ, อ่ะ, ปะ), English mixed in. Don't make it formal.
When someone speaks English, keep it in English letters as said; don't turn it into Thai.
Thai puts a space between phrases and sentences; add those spaces where the recogniser left them out.
Keep every line id and return every line. Don't merge lines: timing comes from the audio. You may move a word or two across the boundary between neighbouring lines when a line clearly ends with the start of the next sentence (for example a question's ending stuck to the start of the answer).
parts: when one line holds two speakers, or two sentences that should be read separately, also give the \
tidied text cut into pieces in order (joined, they equal th, spaces aside); the line's time is shared out by \
length. Also cut a line holding several short answers or sentences (each ending in ค่ะ, ครับ, นะ, \
a question…) so each can be one person's line. Otherwise leave parts out.
kind: "speech" for talking; "song" when the line is lyrics being sung; "sound" when there are no real \
words (laughing, music, noise). For "sound" lines put a short Thai-free description in th like "(笑)" or "♪".
suspect: true when you still think the words may be wrong after your changes (you'll be asked again later \
with a fresh listen), and say why in reason. Lines marked unsure=true had low recogniser confidence.
A translation written by people (for example the video's English captions) may be given: it shows what was \
meant, not the Thai words, so never translate it back into Thai. Use it to spot misheard lines: when a Thai \
line's meaning clearly doesn't fit the translation at that time, mark it suspect and say what the translation \
says in reason. Small differences of wording are normal; only flag a real mismatch."""

POLISH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "required": ["id", "th", "kind", "suspect"], "properties": {
                  "id": {"type": "integer"}, "th": {"type": "string"},
                  "kind": {"type": "string", "enum": ["speech", "song", "sound"]},
                  "suspect": {"type": "boolean"}, "reason": {"type": "string"},
                  "parts": {"type": "array", "items": {"type": "string"}}}}}}}


def polish(job, lines, helpers):
    mem = memory.prompt_text("th")

    def run(chunk):
        if not chunk:
            return []
        ref = _helpers_text(helpers, "original", chunk[0]["start"], chunk[-1]["end"])
        meant = _meaning_text(helpers, chunk[0]["start"], chunk[-1]["end"]) if job["options"].get("subs_check") else ""
        prompt = "\n\n".join(x for x in (
            _context(job),
            f"Memory (names, words and rules learned from the user's earlier feedback):\n{mem}" if mem else "",
            f"Reference transcript(s) from the user:\n{ref}" if ref else "",
            f"Translation(s) written by people (what was meant; check the Thai against it):\n{meant}" if meant else "",
            "Captions to tidy (one JSON object per line):\n" + _lines_text(chunk, ("th",)),
            "Return every line.") if x)
        return ask(POLISH_SYSTEM, prompt, POLISH_SCHEMA, job["dir"])["lines"]

    return [x for part in _parallel(run, _chunks(lines)) for x in part]


# ---------------------------------------------------------------- translate

TRANSLATE_SYSTEM = """You write Traditional Chinese subtitles (Taiwan usage: 繁體中文, 台灣用語) for Thai videos. \
Write what a Taiwanese subtitler would: natural spoken Chinese that fits on screen, not word-for-word. \
Keep each line's meaning in that line so it matches the timing; you may move a word between neighbouring \
lines when Thai and Chinese word order differ. Keep the tone (teasing, polite, shy, angry). Subtitle punctuation: no 。 at the end of a line; ？ and ！ are fine. \
Names: keep people's nicknames as the user's memory spells them; otherwise use the common fandom \
spelling, or keep the Thai nickname in Latin letters (e.g. Milk, Love) when unsure. \
Lines in English (or mixed) get translated into Chinese too. Lines with kind "song" are sung lyrics: don't translate them, write "♪" (the user can type their own). \
Lines with kind "sound": a short bracketed note like "（笑）" or "（音樂）", or "" if nothing is worth showing. \
Follow the user's memory rules; they win over these defaults. \
If a reference translation from the user is given, use it as the main guide: keep its wording where it \
fits the line, and fix it only where it is clearly wrong or doesn't match the Thai.
unsure: true when the Thai line itself looks garbled and you had to guess."""

TRANSLATE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "required": ["id", "zh", "unsure"], "properties": {
                  "id": {"type": "integer"}, "zh": {"type": "string"}, "unsure": {"type": "boolean"}}}}}}


def translate(job, lines, helpers):
    mem = memory.prompt_text("zh")
    by_id = {l["id"]: l for l in lines}

    def run(chunk):
        if not chunk:
            return []
        i0 = lines.index(chunk[0])
        before = lines[max(0, i0 - 6):i0]
        ref = _helpers_text(helpers, "translation", chunk[0]["start"], chunk[-1]["end"])
        prompt = "\n\n".join(x for x in (
            _context(job),
            f"Memory (learned from the user's feedback; follow it):\n{mem}" if mem else "",
            f"Reference translation(s) from the user:\n{ref}" if ref else "",
            "The lines just before these, for context (don't return them):\n" + _lines_text(before, ("th", "zh")) if before else "",
            "Translate these lines:\n" + _lines_text(chunk, ("th", "kind"))) if x)
        return ask(TRANSLATE_SYSTEM, prompt, TRANSLATE_SCHEMA, job["dir"], effort="high")["lines"]

    out = [x for part in _parallel(run, _chunks(lines)) for x in part]
    return [x for x in out if x["id"] in by_id]


# ---------------------------------------------------------------- self-check

REVIEW_SYSTEM = """You check finished bilingual captions (Thai heard by a speech recogniser, Traditional Chinese \
translation) before the user sees them. Find real problems only:
- "heard": the Thai looks misheard (nonsense, wrong word for the context, a name spelled differently from \
elsewhere, words that don't fit the conversation). Lines with unsure=true deserve a closer look.
- "translation": the Chinese is wrong, unnatural, inconsistent with other lines (names, terms, how people \
address each other), Simplified characters, or mainland wording where Taiwan says it differently.
- "timing": a line is far too long to read in its time (more than about 7 Chinese characters per second).
For "translation" problems give the corrected Chinese in fix. For "heard" problems the line will be listened \
to again; say what you suspect in why. Don't report lines that are fine. Don't rewrite style for taste.
Subtitles written by people (the video's own captions) may be given with times. They're the best evidence: \
a Thai line whose meaning doesn't fit them at that time is "heard"; a Chinese line that contradicts them is \
"translation". They may be split or timed a little differently from these lines; small wording differences \
are normal."""

REVIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["problems"], "properties": {
    "problems": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["id", "type", "why"], "properties": {
                     "id": {"type": "integer"},
                     "type": {"type": "string", "enum": ["heard", "translation", "timing"]},
                     "why": {"type": "string"}, "fix": {"type": "string"}}}}}}


def review(job, lines, helpers=()):
    mem = memory.prompt_text("both")

    def run(chunk):
        if not chunk:
            return []
        prompt = "\n\n".join(x for x in (
            _context(job),
            f"Memory (the user's rules):\n{mem}" if mem else "",
            *_refs_for(helpers, chunk[0]["start"], chunk[-1]["end"]),
            "Captions:\n" + _lines_text(chunk, ("th", "zh", "kind"))) if x)
        return ask(REVIEW_SYSTEM, prompt, REVIEW_SCHEMA, job["dir"])["problems"]

    return [x for part in _parallel(run, _chunks(lines, 150)) for x in part]


# ---------------------------------------------------------------- fix what was flagged

FIX_SYSTEM = """You fix bilingual captions (Thai + Traditional Chinese, Taiwan usage) that the user or an \
automatic check flagged. You cannot hear the audio. For lines flagged "heard" you get fresh attempts from \
the speech recogniser (listening again, some with the music removed); the window each attempt covers is a \
little wider than the line, so pick out the part that belongs to this line. Choose the reading that best \
fits the attempts, the conversation, the user's note and the memory; when the attempts agree with the old \
text, keep it. Subtitles written by people for the line's time (subtitles_by_people) are strong evidence: \
Thai ones show the words, translations show the meaning (pick the attempt that means that). Then make the \
Chinese match the Thai.
Lines with a user note: the note is the user's own feedback and is the most important input. If the user \
typed the correct text, use it.
You may also return a context line (by its id) when this fix makes it wrong too: a word split across the two lines, or a neighbour whose translation no longer fits. Return only lines you looked at.
explain is shown to the user: one short plain sentence about what changed and why. Call the earlier text "the old line" (it came from the automatic first pass); never say "you" or "your" for it.
lessons: what the user's feedback teaches that should apply to FUTURE videos too, written as short \
instructions. Only from what the user's notes say, never from your own guesses (not a title or spelling you inferred). Types: "name" (a person's name and how to \
write it in Thai and Chinese), "word" (a Thai word/phrase and the Chinese the user wants), "style" (a general \
translation or captioning rule). Skip lessons that only fit this one line."""

FIX_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines", "lessons"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "required": ["id", "th", "zh", "explain"], "properties": {
                  "id": {"type": "integer"}, "th": {"type": "string"}, "zh": {"type": "string"},
                  "explain": {"type": "string", "description": "one short sentence for the user: what changed and why"}}}},
    "lessons": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["type", "rule"], "properties": {
                    "type": {"type": "string", "enum": ["name", "word", "style"]},
                    "th": {"type": "string"}, "zh": {"type": "string"}, "rule": {"type": "string"}}}}}}


def fix(job, lines, targets, relistened, helpers=()):
    """targets: lines to fix (with flag/note). relistened: {id: [attempt texts]}."""
    by_id = {l["id"]: l for l in lines}
    mem = memory.prompt_text("both")
    blocks = []
    for t in targets:
        i = lines.index(by_id[t["id"]])
        ctx = lines[max(0, i - 3):i + 4]
        b = {"id": t["id"], "flag": t.get("flag"), "user_note": t.get("note") or "",
             "found_by": "user" if t.get("by") == "user" else "automatic check",
             "current": {"th": t["th"], "zh": t.get("zh", "")},
             "context": [{"id": c["id"], "th": c["th"], "zh": c.get("zh", "")} for c in ctx if c["id"] != t["id"]]}
        if t["id"] in relistened:
            b["listened_again"] = relistened[t["id"]]
        subs = [f"[{h['label']}] " + " / ".join(i["text"] for i in h["items"]
                                               if i["end"] >= t["start"] - 1 and i["start"] <= t["end"] + 1)
                for h in helpers if h.get("items")]
        subs = [x for x in subs if not x.endswith("] ")]
        if subs:
            b["subtitles_by_people"] = subs
        blocks.append(json.dumps(b, ensure_ascii=False))
    prompt = "\n\n".join(x for x in (
        _context(job),
        f"Memory (learned from earlier feedback):\n{mem}" if mem else "",
        "Lines to fix (one JSON object each):\n" + "\n".join(blocks)) if x)
    return ask(FIX_SYSTEM, prompt, FIX_SCHEMA, job["dir"], effort="high")


# ---------------------------------------------------------------- rebuild a stretch you marked

REBUILD_SYSTEM = """You rebuild the captions for one stretch of a Thai video that the user marked, usually \
because lines were skipped, misheard, or badly split. You cannot hear the audio. You get several fresh \
transcripts of the stretch from speech recognisers, each with timed segments (some in Thai, some letting the \
recogniser pick the language, which catches English that a Thai-only pass drops), the old captions, the \
conversation around it, and the user's note, which matters most. Subtitles written by people for the stretch \
may be given too: Thai ones show the words; translations show what was meant, so pick and correct the \
transcripts to fit that meaning (never translate them back into Thai). Their timing can be off by a second \
or more (they were timed by someone else), so times always come from the transcripts. If no transcript caught \
anything a subtitle shows, write nothing for it: the subtitle may be timed for a moment just before or after.
Write the captions for the whole stretch from scratch: original-language text (Thai, or English as spoken) and \
Traditional Chinese (Taiwan usage, no 。 at line ends). Take start/end times from the transcript segments (you may \
split a segment's time in proportion to its text); keep each line short enough to read (about 34 Thai letters, \
under 6 seconds). Lines marked "keep" were written by the user: don't repeat or change them, write around them.
When two people talk at the same time, write each person's words as a line of its own (their times may overlap); \
don't merge two speakers into one line.
Ignore a transcript that only repeats one word over and over: that's the recogniser stuck, not speech. Don't repeat \
the lines just before or after the stretch.
unsure: true on any line where you had to guess (a name, a title, words none of the transcripts agree on), \
so the user checks it. explain: one plain sentence for the user about what changed.
lessons: only what the user's note itself says that applies to future videos (types name / word / style), else \
empty. Never turn your own guesses into lessons (not a title you think it was, not a spelling you inferred)."""

REBUILD_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines", "explain", "lessons"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "required": ["start", "end", "th", "zh"], "properties": {
                  "start": {"type": "number"}, "end": {"type": "number"}, "th": {"type": "string"},
                  "zh": {"type": "string"}, "kind": {"type": "string", "enum": ["speech", "song", "sound"]},
                  "unsure": {"type": "boolean"}}}},
    "explain": {"type": "string"},
    "lessons": FIX_SCHEMA["properties"]["lessons"]}}


def rebuild(job, lines, start, end, inside, keep, attempts, note, helpers=(), why=""):
    idx = [i for i, l in enumerate(lines) if l in inside]
    i0 = idx[0] if idx else next((i for i, l in enumerate(lines) if l["start"] >= start), len(lines))
    i1 = (idx[-1] + 1) if idx else i0
    before, after = lines[max(0, i0 - 5):i0], lines[i1:i1 + 3]
    mem = memory.prompt_text("both")
    parts = [
        _context(job),
        f"Memory (learned from earlier feedback):\n{mem}" if mem else "",
        f"The user marked {start:.1f}s to {end:.1f}s." + (f" Their note: \"{note}\"" if note else
            f" (Found automatically: {why or 'the voice detector hears talking here but there were no captions for it'}.)"),
        *_refs_for(helpers, start - 1, end + 1),
        "Lines just before (context only):\n" + _lines_text(before, ("th", "zh")) if before else "",
        "Old captions in the stretch:\n" + (_lines_text(inside, ("th", "zh")) or "(none: this part had no captions)"),
        "Lines to keep exactly (the user's own):\n" + _lines_text(keep, ("th", "zh")) if keep else "",
        "Fresh transcripts:\n" + "\n".join(json.dumps(a, ensure_ascii=False) for a in attempts) if attempts else
        "Fresh transcripts: none came back (maybe music or silence).",
        "Lines just after (context only):\n" + _lines_text(after, ("th", "zh")) if after else "",
    ]
    return ask(REBUILD_SYSTEM, "\n\n".join(x for x in parts if x), REBUILD_SCHEMA, job["dir"], effort="high")


# ---------------------------------------------------------------- touches: emoji and little notes

TOUCH_SYSTEM = """You add playful touches to a fan-made captioned video, the way Taiwanese and Thai fan editors \
do: an emoji or a short Chinese note that shows what words can't, such as (臉紅)💗 when someone gets shy, \
(偷笑)🤭, (尷尬)😅, 心動💓, 噗哧😂, ✨ on a cute moment, 👀 when someone sneaks a look, (無奈) for a sigh, \
or a tiny name tag. You see contact sheets (frames labelled with their time) and the captions.
Pick only moments that really earn one: about one every 20 to 40 seconds, fewer when nothing is happening. \
Never repeat what the caption already says. Keep text very short (1–6 characters plus emoji).
Place each touch where it fits on the frame without covering faces or the captions at the bottom: x and y \
are fractions of the frame width and height (0,0 top-left), usually beside a person's head. \
kind "bubble" puts it on a small white rounded label (good for name tags or short notes); "plain" is outlined text.
start/end in seconds: show it for 1.5 to 4 seconds around the moment."""

TOUCH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["touches"], "properties": {
    "touches": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["start", "end", "text", "x", "y", "kind", "why"], "properties": {
                    "start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"},
                    "x": {"type": "number"}, "y": {"type": "number"},
                    "kind": {"type": "string", "enum": ["plain", "bubble"]},
                    "why": {"type": "string", "description": "a few words: what happens at that moment"}}}}}}


def suggest_touches(job, lines, sheets, every):
    mem = memory.prompt_text("both")
    prompt = "\n\n".join(x for x in (
        _context(job),
        f"Memory (the user's names and rules):\n{mem}" if mem else "",
        f"Contact sheets: frames every {every} seconds, 16 per sheet, left to right then top to bottom; the yellow "
        "label on each frame is its time.",
        "Captions:\n" + _lines_text(lines, ("th", "zh"))) if x)
    return ask(TOUCH_SYSTEM, prompt, TOUCH_SCHEMA, job["dir"], images=sheets, effort="high")


# ---------------------------------------------------------------- who says each line

SPEAKER_SYSTEM = """You work out who says each caption line in a Thai video, from the words alone: who is \
being addressed (พี่มิ้ลค์ is said TO Milk, by someone else), people naming themselves (เลิฟค่ะ, Thai speakers \
often use their own name for "I"), question and answer turns, and the lines the user already assigned (true). \
Give a person's id only when the text gives a real reason; otherwise "" (unknown). Don't guess by alternating."""

SPEAKER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
              "required": ["id", "speaker"], "properties": {
                  "id": {"type": "integer"}, "speaker": {"type": "string"}}}}}}


def guess_speakers(job, lines, people):
    who = "\n".join(f'- id "{p["id"]}": {p.get("name") or "(no name)"}' for p in people)
    rows = []
    for l in lines:
        row = {"id": l["id"], "time": f"{l['start']:.1f}", "th": l.get("th", ""), "zh": l.get("zh", "")}
        if l.get("speaker") and not l.get("speaker_guess"):
            row["speaker"], row["by_user"] = l["speaker"], True
        rows.append(json.dumps(row, ensure_ascii=False))
    prompt = "\n\n".join(x for x in (_context(job), "People:\n" + who, "Lines:\n" + "\n".join(rows)) if x)
    return ask(SPEAKER_SYSTEM, prompt, SPEAKER_SCHEMA, job["dir"], effort="low")
