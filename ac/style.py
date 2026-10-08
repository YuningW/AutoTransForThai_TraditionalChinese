"""How captions and touches (emoji, little notes) look, and drawing them for burning in.

Sizes are relative so a style fits any video: the Chinese line is `size` × 5.8% of the
picture's short side, Thai is `th_scale` of that, outlines and shadows are a share of
the font size. The page previews the same numbers with CSS (web/app.js: styleCss).
"""
import hashlib
import json
import subprocess
import threading
from pathlib import Path

from . import models

SRC = Path(__file__).with_name("render.swift")
BIN = models.CACHE.parent / "bin" / "render"

DEFAULT = {
    "theme": "classic",
    "zh_font": "PingFang TC", "th_font": "Sukhumvit Set", "bold": False,
    "size": 1.0, "th_scale": 0.76,
    "color": "#FFFFFF", "th_color": "#FFF4E8",
    "outline": 0.07, "outline_color": "#000000",
    "shadow": 0.05,
    "box": False, "box_color": "#000000A0",
    "position": "bottom",          # bottom | top | custom
    "y": 0.94,                     # custom: where the bottom of the captions sits (0 top .. 1 bottom)
    "order": "th_above",           # th_above | zh_above
}

THEMES = {
    "classic": {"label": "經典白 Classic"},
    "yellow": {"label": "字幕黃 Fansub yellow", "color": "#FFE14D", "th_color": "#FFFFFF", "outline": 0.08},
    "boxed": {"label": "黑底框 Boxed", "outline": 0.0, "shadow": 0.0, "box": True, "box_color": "#000000A6"},
    "milktea": {"label": "奶茶 Milk tea", "zh_font": "Yuanti TC", "bold": True, "color": "#FFF7EC",
                "th_color": "#FFF7EC", "outline": 0.11, "outline_color": "#8B5E3C", "shadow": 0.0},
    "pink": {"label": "粉嫩 Soft pink", "zh_font": "Yuanti TC", "bold": True, "color": "#FFFFFF",
             "th_color": "#FFE3EF", "outline": 0.12, "outline_color": "#F06A9F", "shadow": 0.04},
    "handwritten": {"label": "手寫 Handwritten", "zh_font": "Hannotate TC", "bold": True, "color": "#FFFFFF",
                    "outline": 0.1, "outline_color": "#3A2A1A"},
    "cute": {"label": "娃娃 Cute", "zh_font": "Wawati TC", "color": "#FFFFFF", "th_color": "#FFFFFF",
             "outline": 0.12, "outline_color": "#5B8DEF", "shadow": 0.0},
    "night": {"label": "夜空 Night glow", "color": "#E8F0FF", "th_color": "#E8F0FF", "outline": 0.05,
              "outline_color": "#1D2550", "shadow": 0.22},
}

# Fonts worth offering, by what they look like. The page only lists the ones this Mac has.
ZH_FONTS = [
    ("PingFang TC", "蘋方 (clean)"), ("Hiragino Sans TC", "冬青黑體"), ("Heiti TC", "黑體"),
    ("Lantinghei TC", "蘭亭黑"), ("Yuanti TC", "圓體 (rounded)"), ("Yuppy TC", "雅痞 (playful)"),
    ("Wawati TC", "娃娃體 (cute)"), ("HanziPen TC", "翩翩體 (pen)"), ("Hannotate TC", "手札體 (handwritten)"),
    ("Kaiti TC", "楷體 (brush)"), ("BiauKaiTC", "標楷體"), ("Songti TC", "宋體 (book)"),
    ("Weibei TC", "魏碑 (bold brush)"), ("Libian TC", "隸變 (clerical)"), ("Baoli TC", "報隸"),
    ("LingWai TC", "凌慧體 (calligraphy)"), ("Xingkai TC", "行楷 (running script)"),
]
TH_FONTS = [
    ("Sukhumvit Set", "Sukhumvit (clean)"), ("Thonburi", "Thonburi"), ("Ayuthaya", "Ayuthaya (classic)"),
    ("Krungthep", "Krungthep (bold)"), ("Silom", "Silom (rounded)"), ("Sathu", "Sathu (serif)"),
]

TOUCH_DEFAULT = {"size": 1.3, "font": "", "color": "#FFFFFF", "outline_color": "#F06A9F", "kind": "plain"}


def merged(style=None):
    s = dict(DEFAULT)
    theme = (style or {}).get("theme")
    if theme in THEMES:
        s.update({k: v for k, v in THEMES[theme].items() if k != "label"})
    s.update({k: v for k, v in (style or {}).items() if k in DEFAULT and v is not None})
    return s


def base_px(w, h, style):
    return min(w, h) * 0.058 * float(style["size"])


def caption_block(line, which, w, h, style, speakers=None):
    """Caption line(s) on screen together -> one renderer block. `line` may be a list: people talking
    at once each get their own rows, earliest first, in their own colour. which: zh | th | both."""
    s = style
    group = line if isinstance(line, list) else [line]
    colours = {p["id"]: p.get("color") for p in speakers or [] if p.get("color")}
    zh_px = base_px(w, h, s)
    th_px = zh_px * float(s["th_scale"]) if which == "both" else zh_px

    def row(text, fam, px, col):
        return {"text": text, "font": fam, "size": round(px, 1), "color": col, "bold": bool(s["bold"]),
                "stroke": round(px * float(s["outline"]), 1), "stroke_color": s["outline_color"],
                "shadow": round(px * float(s["shadow"]), 1)}

    rows = []
    for l in sorted(group, key=lambda x: x.get("start", 0)):
        th, zh = (l.get("th") or "").strip(), (l.get("zh") or "").strip()
        if l.get("kind") == "sound":
            th = ""
        own = colours.get(l.get("speaker"))
        zh_row = row(zh, s["zh_font"], zh_px, own or s["color"]) if which in ("zh", "both") and zh else None
        th_row = row(th, s["th_font"], th_px, own or (s["th_color"] if which == "both" else s["color"])) \
            if which in ("th", "both") and th else None
        pair = (th_row, zh_row) if s["order"] == "th_above" else (zh_row, th_row)
        rows += [r for r in pair if r]
    if not rows:
        return None
    if s["position"] == "top":
        y, anchor = 0.05, "top"
    elif s["position"] == "custom":
        y, anchor = float(s["y"]), "bottom"
    else:
        y, anchor = 0.94, "bottom"
    box = {"color": s["box_color"], "pad": round(zh_px * 0.32), "radius": round(zh_px * 0.25)} if s["box"] else None
    return {"x": 0.5, "y": y, "anchor": anchor, "maxw": 0.88, "gap": round(zh_px * 0.12), "box": box, "rows": rows}


def touch_block(t, w, h, style):
    """A touch: emoji or a little note placed anywhere; or your own text or logo."""
    opacity = float(t.get("opacity") if t.get("opacity") is not None else 1.0)
    if t.get("kind") == "image":
        from . import paths
        f = next((f for f in sorted(paths.LOGOS.glob(f"{t.get('image')}.*"))
                  if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".tif", ".tiff")), None)
        if not f:
            return None
        return {"image": str(f), "x": float(t.get("x", 0.1)), "y": float(t.get("y", 0.1)),
                "w": float(t.get("w") or 0.15), "opacity": opacity}
    px = base_px(w, h, style) * float(t.get("size") or 1.3)
    if t.get("kind") == "text":                # your own text: a title, a credit, your name
        return {"x": float(t.get("x", 0.85)), "y": float(t.get("y", 0.08)), "anchor": "center", "maxw": 0.9, "gap": 0,
                "opacity": opacity, "box": None,
                "rows": [{"text": t.get("text", ""), "font": t.get("font") or style["zh_font"], "size": round(px, 1),
                          "color": t.get("color") or "#FFFFFF", "bold": bool(t.get("bold", True)),
                          "stroke": round(px * float(t.get("outline", 0.08)), 1), "stroke_color": t.get("outline_color") or "#000000",
                          "shadow": round(px * 0.04, 1)}]}
    bubble = t.get("kind") == "bubble"
    return {"x": float(t.get("x", 0.8)), "y": float(t.get("y", 0.2)), "anchor": "center", "maxw": 0.6, "opacity": opacity,
            "gap": 0, "box": {"color": "#FFFFFFEE", "pad": round(px * 0.35), "radius": round(px * 0.6)} if bubble else None,
            "rows": [{"text": t.get("text", ""), "font": t.get("font") or style["zh_font"], "size": round(px, 1),
                      "color": "#3A2A3A" if bubble else (t.get("color") or "#FFFFFF"), "bold": True,
                      "stroke": 0 if bubble else round(px * 0.1, 1),
                      "stroke_color": t.get("outline_color") or "#F06A9F", "shadow": 0 if bubble else round(px * 0.04, 1)}]}


# ---------------------------------------------------------------- the renderer process

class Renderer:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None

    def _binary(self):
        if not BIN.exists() or BIN.stat().st_mtime < SRC.stat().st_mtime:
            BIN.parent.mkdir(parents=True, exist_ok=True)
            p = subprocess.run(["swiftc", "-O", "-o", str(BIN), str(SRC)], capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError("Couldn't build the caption renderer (needs Xcode's command-line tools: "
                                   "xcode-select --install). " + p.stderr[-300:])
        return BIN

    def render(self, out, w, h, blocks):
        job = json.dumps({"out": str(out), "w": int(w), "h": int(h), "blocks": blocks}, ensure_ascii=False)
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                self.proc = subprocess.Popen([str(self._binary())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             text=True, bufsize=1)
            self.proc.stdin.write(job + "\n")
            self.proc.stdin.flush()
            r = self.proc.stdout.readline().strip()
        if r != "ok":
            raise RuntimeError("Drawing captions failed: " + (r or "the renderer stopped"))

    def fonts(self):
        p = subprocess.run([str(self._binary()), "fonts"], capture_output=True, text=True)
        return set(p.stdout.splitlines())


renderer = Renderer()


def available_fonts():
    have = renderer.fonts()
    return {"zh": [{"family": f, "label": l} for f, l in ZH_FONTS if f in have],
            "th": [{"family": f, "label": l} for f, l in TH_FONTS if f in have]}


# ---------------------------------------------------------------- frames for burning in

def timeline(lines, touches, which):
    """[(start, end, [items])]: each stretch where the same captions and touches are on screen."""
    items = []
    for l in lines:
        if which in ("zh", "both") and (l.get("zh") or "").strip() or which in ("th", "both") and (l.get("th") or "").strip():
            items.append(("line", l))
    items += [("touch", t) for t in touches if (t.get("text") or "").strip() or t.get("kind") == "image"]
    cuts = sorted({0.0} | {round(x[1]["start"], 3) for x in items} | {round(x[1]["end"], 3) for x in items})
    spans = []
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        on = [x for x in items if x[1]["start"] <= mid < x[1]["end"]]
        if spans and [id(x[1]) for x in on] == [id(x[1]) for x in spans[-1][2]]:
            spans[-1] = (spans[-1][0], b, on)
        else:
            spans.append((a, b, on))
    return spans


def frames(lines, touches, which, w, h, style, folder, on_progress=None, speakers=None):
    """Render one PNG per distinct screen and return an ffmpeg concat list for them."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    s = merged(style)
    blank = folder / "blank.png"
    renderer.render(blank, w, h, [])
    spans = timeline(lines, touches, which)
    entries = []
    for i, (a, b, on) in enumerate(spans):
        blocks = []
        talking = [x for kind, x in on if kind == "line"]
        if talking:
            blk = caption_block(talking, which, w, h, s, speakers)
            if blk:
                blocks.append(blk)
        blocks += [b for b in (touch_block(x, w, h, s) for kind, x in on if kind == "touch") if b]
        if blocks:
            key = hashlib.sha1(json.dumps(blocks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            png = folder / f"{key}.png"
            if not png.exists():
                renderer.render(png, w, h, blocks)
        else:
            png = blank
        entries.append((png, b - a))
        if on_progress and i % 10 == 0:
            on_progress(i / max(1, len(spans)))
    text = "ffconcat version 1.0\n"
    for png, dur in entries:
        text += f"file '{png.name}'\nduration {max(dur, 0.001):.3f}\n"
    text += f"file '{(entries[-1][0] if entries else blank).name}'\n"
    lst = folder / "frames.txt"
    lst.write_text(text)
    return lst


def still(line, touches, which, w, h, style, out):
    """One frame, for checking how a style looks."""
    s = merged(style)
    blocks = [b for b in [caption_block(line, which, w, h, s)] if b] + [touch_block(t, w, h, s) for t in touches]
    renderer.render(out, w, h, blocks)
