"""What the tool has learned from your feedback, kept for every future video.

work/memory.json
  names    [{"id", "th", "zh", "note"}]   people: how to spell them in Thai and Chinese
  words    [{"id", "th", "zh", "note"}]   words/phrases and the Chinese you want for them
  rules    [{"id", "text"}]               general style rules ("use 妳 for women", ...)
  examples [{"th", "zh_before", "zh_after", "th_before", "note"}]  your recent corrections

Names and words also go to Whisper as a hint, so it spells them right while listening.
"""
import json
import threading
import time
import uuid

from . import paths

KEEP_EXAMPLES = 40
KEEP_PEOPLE = 30
_lock = threading.Lock()
EMPTY = {"names": [], "words": [], "rules": [], "examples": [], "people": []}


def load():
    try:
        m = json.loads(paths.MEMORY.read_text())
    except (OSError, ValueError):
        m = {}
    return {k: list(m.get(k) or []) for k in EMPTY}


def _save(m):
    paths.MEMORY.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.MEMORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    tmp.replace(paths.MEMORY)


def _new_id():
    return uuid.uuid4().hex[:8]


def add(kind, th="", zh="", text="", note="", source=""):
    """Add or update a name/word (matched on the Thai) or a rule (matched on its text)."""
    th, zh, text = (th or "").strip(), (zh or "").strip(), (text or "").strip()
    with _lock:
        m = load()
        if kind in ("names", "words"):
            if not th and not zh:
                return m
            for e in m[kind]:
                if th and e.get("th") == th:
                    e.update(zh=zh or e.get("zh", ""), note=note or e.get("note", ""), updated=time.time())
                    break
            else:
                m[kind].append({"id": _new_id(), "th": th, "zh": zh, "note": note, "source": source, "updated": time.time()})
        elif kind == "rules":
            if text and text not in [r["text"] for r in m["rules"]]:
                m["rules"].append({"id": _new_id(), "text": text, "source": source, "updated": time.time()})
        _save(m)
        return m


def learn(lessons, source=""):
    """Lessons Claude drew from your notes -> memory. Returns what was added, for the page."""
    added = []
    for l in lessons or []:
        t = l.get("type")
        if t == "name" and (l.get("th") or l.get("zh")):
            add("names", l.get("th"), l.get("zh"), note=l.get("rule", ""), source=source)
        elif t == "word" and l.get("th"):
            add("words", l.get("th"), l.get("zh"), note=l.get("rule", ""), source=source)
        elif l.get("rule"):
            add("rules", text=l["rule"], source=source)
        else:
            continue
        added.append(l)
    return added


def remember_example(th, zh_before, zh_after, th_before="", note=""):
    with _lock:
        m = load()
        m["examples"].append({"th": th, "th_before": th_before, "zh_before": zh_before,
                              "zh_after": zh_after, "note": note, "at": time.time()})
        m["examples"] = m["examples"][-KEEP_EXAMPLES:]
        _save(m)


def edit(kind, eid, changes):
    with _lock:
        m = load()
        for e in m.get(kind, []):
            if e.get("id") == eid:
                e.update({k: v for k, v in changes.items() if k in ("th", "zh", "note", "text", "name", "color")})
                e["updated"] = time.time()
        _save(m)
        return m


def remove(kind, eid):
    with _lock:
        m = load()
        m[kind] = [e for e in m.get(kind, []) if e.get("id") != eid]
        _save(m)
        return m


def remember_people(people):
    """Your usual people and their caption colours, so new videos start with them (voiceprints kept).
    Matched by id first, so renaming someone in a video renames them here too."""
    with _lock:
        m = load()
        for p in people or []:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            pid = p.get("id")
            old = next((q for q in m["people"] if pid and pid in [q.get("id"), *(q.get("ids") or [])]), None) \
                or next((q for q in m["people"] if q.get("name") == name), None)
            if old:
                old.update(name=name, color=p.get("color") or old.get("color"), id=old.get("id") or pid or _new_id())
                if "font" in p or old.get("font"):
                    old["font"] = p.get("font") or None     # their own font (or back to the video's)
                if pid and pid != old["id"] and pid not in (old.get("ids") or []):
                    old["ids"] = (old.get("ids") or []) + [pid]    # the same person under another video's id
            else:
                m["people"].append({"id": pid or _new_id(), "name": name, "color": p.get("color"),
                                    **({"font": p["font"]} if p.get("font") else {})})
        # one entry per name (a rename can make two the same: keep the one with a voice)
        seen, keep = set(), []
        for q in sorted(m["people"], key=lambda q: -int(q.get("voice_n") or 0)):
            if q.get("name") not in seen:
                seen.add(q.get("name"))
                keep.append(q)
        m["people"] = keep[-KEEP_PEOPLE:]
        _save(m)


def learn_voices(prints):
    """prints: {name: (unit voiceprint list, n lines)}. Folded into what's remembered, weighted by lines."""
    import numpy as np
    with _lock:
        m = load()
        for p in m["people"]:
            if p.get("name") in prints:
                vec, n = prints[p["name"]]
                old_n = int(p.get("voice_n") or 0)
                if p.get("voice") and old_n:
                    v = (np.array(p["voice"]) * old_n + np.array(vec) * n) / (old_n + n)
                else:
                    v = np.array(vec)
                v = v / (np.linalg.norm(v) + 1e-9)
                p["voice"], p["voice_n"] = [round(float(x), 5) for x in v], min(old_n + n, 200)
        _save(m)


def remembered_voices():
    """{name: (unit voiceprint, n)} and {id: ...} for people whose voice has been learned."""
    out = {}
    for p in load()["people"]:
        if p.get("voice"):
            v = (p["voice"], int(p.get("voice_n") or 0))
            out[p["name"]] = v
            for i in [p.get("id"), *(p.get("ids") or [])]:
                if i:
                    out["id:" + i] = v
    return out


def forget_voice(pid):
    with _lock:
        m = load()
        for p in m["people"]:
            if p.get("id") == pid:
                p.pop("voice", None)
                p.pop("voice_n", None)
        _save(m)
        return m


def prompt_text(scope="both"):
    """Memory as text for Claude. scope "th" leaves out Chinese-only style rules."""
    m = load()
    out = []
    if m["names"]:
        out.append("Names (Thai → Chinese):\n" + "\n".join(
            f"- {e['th']} → {e['zh']}" + (f"  ({e['note']})" if e.get("note") else "") for e in m["names"]))
    if m["words"]:
        out.append("Words and phrases (Thai → Chinese the user wants):\n" + "\n".join(
            f"- {e['th']} → {e['zh']}" + (f"  ({e['note']})" if e.get("note") else "") for e in m["words"]))
    if m["rules"] and scope != "th":
        out.append("Rules:\n" + "\n".join(f"- {r['text']}" for r in m["rules"]))
    if m["examples"] and scope != "th":
        ex = m["examples"][-15:]
        out.append("Recent corrections by the user (before → after):\n" + "\n".join(
            f"- {e['th']}: {e['zh_before']} → {e['zh_after']}" + (f"  (note: {e['note']})" if e.get("note") else "")
            for e in ex if e.get("zh_before") != e.get("zh_after")))
    return "\n\n".join(out)


def whisper_hint():
    """A short Thai prompt that nudges Whisper toward the right spelling of names and words."""
    m = load()
    terms = [e["th"] for e in m["names"] + m["words"] if e.get("th")]
    return (" ".join(terms))[:220]
