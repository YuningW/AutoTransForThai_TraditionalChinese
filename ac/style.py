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
    "huninn": {"label": "粉圓 Round", "zh_font": "Huninn", "color": "#FFFFFF", "th_color": "#FFFFFF",
               "outline": 0.13, "outline_color": "#4A3B5C", "shadow": 0.0},
    "wenkai": {"label": "文楷 Brush", "zh_font": "LXGW WenKai TC", "bold": True, "color": "#FFFDF5",
               "th_color": "#FFFDF5", "outline": 0.09, "outline_color": "#2B2420", "shadow": 0.06},
    "gensen": {"label": "源泉 Soft round", "zh_font": "GenSenRounded2 TW", "bold": True, "color": "#FFFFFF",
               "th_color": "#FFFFFF", "outline": 0.12, "outline_color": "#3D6E9E", "shadow": 0.0},
    "jason": {"label": "清松 Diary", "zh_font": "JasonHandWriting1", "color": "#FFFDF7", "th_color": "#FFFDF7",
              "outline": 0.11, "outline_color": "#6B4A3A", "shadow": 0.03},
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
    # free, open-source (SIL OFL) fonts: installed in ~/Library/Fonts
    ("Huninn", "粉圓 (round, cute) · free"), ("LXGW WenKai TC", "霞鶩文楷 (brush handwriting) · free"),
    ("Iansui", "芫荽 (casual handwriting) · free"), ("ChenYuluoyan 2.0", "辰宇落雁體 (thin handwriting) · free"),
    ("Chiron Hei HK", "昭源黑體 (clean) · free"), ("Noto Serif TC", "思源宋體 (book) · free"),
    ("Cactus Classical Serif", "仙人掌明體 (old book) · free"),
    ("GenSenRounded2 TW", "源泉圓體 (soft round) · free"), ("Chiron GoRound TC", "昭源圓體 (clean round) · free"),
    ("JasonHandWriting1", "清松手寫體 (cute handwriting) · free"), ("LXGW Marker Gothic", "霞鶩漫黑 (marker pen) · free"),
    ("Chocolate Classical Sans", "朱古力黑體 (retro) · free"), ("WDXL Lubrifont TC", "滑油字 (chunky, loud) · free"),
    ("Cubic 11", "俐方體11號 (pixel, game) · free"),
]
# The free fonts setup installs (family, file in ~/Library/Fonts, weights). Safari won't let a page use
# fonts the user installed (anti-fingerprinting), so the app serves these to the page itself.
FREE_FONTS = [
    ("Huninn", "Huninn-Regular.ttf", "400"),
    ("LXGW WenKai TC", "LXGWWenKaiTC-Regular.ttf", "400"),
    ("LXGW WenKai TC", "LXGWWenKaiTC-Bold.ttf", "700"),
    ("Iansui", "Iansui-Regular.ttf", "400"),
    ("ChenYuluoyan 2.0", "ChenYuluoyan-2.0-Thin.ttf", "400"),
    ("Chiron Hei HK", "ChironHeiHK[wght].ttf", "200 900"),
    ("Noto Serif TC", "NotoSerifTC[wght].ttf", "200 900"),
    ("Cactus Classical Serif", "CactusClassicalSerif-Regular.ttf", "400"),
    ("GenSenRounded2 TW", "GenSenRounded2TW-R.otf", "400"),
    ("GenSenRounded2 TW", "GenSenRounded2TW-B.otf", "700"),
    ("Chiron GoRound TC", "ChironGoRoundTC[wght].ttf", "200 900"),
    ("JasonHandWriting1", "JasonHandwriting1-Regular.ttf", "400"),
    ("LXGW Marker Gothic", "LXGWMarkerGothic-Regular.ttf", "400"),
    ("Chocolate Classical Sans", "ChocolateClassicalSans-Regular.ttf", "400"),
    ("WDXL Lubrifont TC", "WDXLLubrifontTC-Regular.ttf", "400"),
    ("Cubic 11", "Cubic_11.ttf", "400"),
]
USER_FONTS = Path.home() / "Library" / "Fonts"


def free_font_faces():
    return [{"family": fam, "file": f, "weight": w} for fam, f, w in FREE_FONTS if (USER_FONTS / f).exists()]


# Most of macOS's Chinese fonts (圓體, 娃娃體, 手札體, 楷體…) are extras the Mac downloads, and Safari won't let a
# page use them either: the page would quietly show its fallback. So the app hands them to the page too, each
# as a single font file (many come in collections, .ttc, which browsers don't read), made the first time.
SYSTEM_FONT_DIR = models.CACHE.parent / "fonts"
_system_faces = None


def system_font_faces():
    """[{family, file, weight}] for the listed Mac fonts (regular and bold of each), for the page's @font-face."""
    global _system_faces
    if _system_faces is not None:
        return _system_faces
    free = {fam for fam, _, _ in FREE_FONTS}
    fams = [f for f, _ in ZH_FONTS + TH_FONTS if f not in free and f != "PingFang TC"]
    try:
        p = subprocess.run([str(renderer._binary()), "fontfiles", *fams], capture_output=True, text=True, timeout=60)
        members = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    except Exception:
        return []
    faces = []
    for fam in fams:
        mine = [m for m in members if m["family"] == fam]
        for want in (400, 700):
            m = min(mine, key=lambda m: (abs(m["weight"] - want), m["weight"]), default=None)
            if m and (want == 400 or m["weight"] >= 600) and not any(f["ps"] == m["ps"] for f in faces):
                faces.append({"family": fam, "file": m["ps"] + Path(m["path"]).suffix.replace(".ttc", ".ttf"),
                              "weight": str(want), "ps": m["ps"], "path": m["path"]})
    _system_faces = faces
    return faces


def system_font_file(name):
    """The single font file for one of system_font_faces(), made from its collection the first time."""
    face = next((f for f in system_font_faces() if f["file"] == name), None)
    if not face:
        return None
    src = Path(face["path"])
    if src.suffix.lower() != ".ttc":
        return src if src.exists() else None
    out = SYSTEM_FONT_DIR / name
    if not out.exists():
        from fontTools.ttLib import TTCollection
        SYSTEM_FONT_DIR.mkdir(parents=True, exist_ok=True)
        for font in TTCollection(str(src), lazy=True):
            if font["name"].getDebugName(6) == face["ps"]:
                tmp = out.with_suffix(".part")
                font.save(str(tmp))
                tmp.rename(out)
                break
    return out if out.exists() else None


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


LOOK_POSITIONS = ("bottom", "top", "custom")
LOOK_SHOW = ("zh", "th", "none")


def clean_look(look):
    """One line's own look, on top of the video's style: position (bottom | top | custom, with y), size
    (× the style's), color, bold, show (zh | th | none: only that language, or hide the line). {} = as all."""
    look = look or {}
    out = {}
    if look.get("position") in LOOK_POSITIONS:
        out["position"] = look["position"]
        if look["position"] == "custom":
            out["y"] = round(min(0.99, max(0.08, float(look.get("y") if look.get("y") is not None else 0.5))), 3)
    if look.get("size") is not None and abs(float(look["size"]) - 1) > 0.01:
        out["size"] = round(min(2.5, max(0.4, float(look["size"]))), 2)
    if isinstance(look.get("color"), str) and look["color"].startswith("#") and len(look["color"]) in (7, 9):
        out["color"] = look["color"]
    if look.get("bold") in (True, False):
        out["bold"] = look["bold"]
    if look.get("show") in LOOK_SHOW:
        out["show"] = look["show"]
    return out


def place_of(line, style):
    """Where a line sits: (position, y). A line with its own position is drawn as its own block."""
    look = line.get("look") or {}
    pos = look.get("position") or style["position"]
    y = look.get("y") if look.get("position") == "custom" else style.get("y")
    return pos, round(float(y if y is not None else 0.94), 3)


def caption_block(line, which, w, h, style, speakers=None):
    """Caption line(s) on screen together -> one renderer block. `line` may be a list: people talking
    at once each get their own rows, earliest first, in their own colour. which: zh | th | both.
    A line's own look (size, colour, bold, which language) changes just its rows."""
    s = style
    group = line if isinstance(line, list) else [line]
    colours = {p["id"]: p.get("color") for p in speakers or [] if p.get("color")}

    def row(text, fam, px, col, bold):
        return {"text": text, "font": fam, "size": round(px, 1), "color": col, "bold": bool(bold),
                "stroke": round(px * float(s["outline"]), 1), "stroke_color": s["outline_color"],
                "shadow": round(px * float(s["shadow"]), 1)}

    rows, biggest = [], 0
    for l in sorted(group, key=lambda x: x.get("start", 0)):
        look = l.get("look") or {}
        show = look.get("show")
        if show == "none":
            continue
        mine = which if not show or which != "both" else show          # "only Chinese" on a both video
        if show and which != "both" and show != which:
            continue                                                   # this line's language isn't in this video
        th, zh = (l.get("th") or "").strip(), (l.get("zh") or "").strip()
        if l.get("kind") == "sound":
            th = ""
        zh_px = base_px(w, h, s) * float(look.get("size") or 1)
        th_px = zh_px * float(s["th_scale"]) if mine == "both" else zh_px
        biggest = max(biggest, zh_px)
        own = look.get("color") or colours.get(l.get("speaker"))
        bold = look.get("bold", s["bold"])
        zh_row = row(zh, s["zh_font"], zh_px, own or s["color"], bold) if mine in ("zh", "both") and zh else None
        th_row = row(th, s["th_font"], th_px, own or (s["th_color"] if mine == "both" else s["color"]), bold) \
            if mine in ("th", "both") and th else None
        pair = (th_row, zh_row) if s["order"] == "th_above" else (zh_row, th_row)
        rows += [r for r in pair if r]
    if not rows:
        return None
    zh_px = biggest
    pos, py = place_of(group[0], s)
    if pos == "top":
        y, anchor = 0.05, "top"
    elif pos == "custom":
        y, anchor = py, "bottom"
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
        blk = {"image": str(f), "x": float(t.get("x", 0.1)), "y": float(t.get("y", 0.1)),
               "w": float(t.get("w") or 0.15), "opacity": opacity}
        # making it stand out on any picture: outline, soft shadow, or a badge behind it
        how, edge = t.get("standout") or "none", t.get("edge_color") or "#000000"
        if how == "outline":
            blk["halo"] = {"color": edge, "width": float(t.get("edge") or 0.012)}
        elif how == "shadow":
            blk["shadow"], blk["shadow_color"] = float(t.get("edge") or 0.012) * 2.5, edge + "D9" if len(edge) == 7 else edge
        elif how in ("badge", "circle"):
            blk["plate"] = {"color": t.get("plate_color") or "#FFFFFFD9", "pad": 0.12,
                            "shape": "circle" if how == "circle" else "round"}
        return blk
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
            fonts_now = USER_FONTS.stat().st_mtime if USER_FONTS.exists() else 0
            if self.proc and self.proc.poll() is None and fonts_now != getattr(self, "fonts_seen", fonts_now):
                self.proc.kill()                 # fonts were added: a fresh renderer sees them
            self.fonts_seen = fonts_now
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
        places = {}
        for x in talking:                     # a line placed somewhere of its own gets its own block
            places.setdefault(place_of(x, s), []).append(x)
        for group in places.values():
            blk = caption_block(group, which, w, h, s, speakers)
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


# ---------------------------------------------------------------- movement (logos, text, emoji)
#
# A moving item is drawn once as a small picture (a sprite); ffmpeg moves, turns or squashes it on every
# frame while saving. Each movement: filters for the sprite, and x/y for where its top-left goes
# (cx, cy = where its centre sits when still; w/h = the sprite's size this frame; W/H = the video's).
MOTIONS = ("float", "wiggle", "flip", "pulse", "spin", "fly", "across")


def motion_filters(motion, period, cx, cy, W, H):
    p = max(0.4, float(period or 2.0))
    still = (f"{cx:.1f}-w/2", f"{cy:.1f}-h/2")
    turn = "c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
    if motion == "float":
        return "", still[0], f"{cy:.1f}-h/2+{0.015 * H:.1f}*sin(2*PI*t/{p})"
    if motion == "wiggle":
        return f"rotate=a='0.16*sin(2*PI*t/{p})':{turn}", *still
    if motion == "spin":
        return f"rotate=a='2*PI*t/{p}':{turn}", *still
    if motion == "flip":                     # turns like a coin: the width shrinks to nothing and back
        return f"scale=w='max(2,iw*abs(cos(PI*t/{p})))':h=ih:eval=frame", *still
    if motion == "pulse":
        k = f"(1+0.09*sin(2*PI*t/{p}))"
        return f"scale=w='iw*{k}':h='ih*{k}':eval=frame", *still
    if motion == "fly":                      # a figure-8 around its spot
        return "", f"{cx:.1f}-w/2+{0.07 * W:.1f}*sin(2*PI*t/{p})", f"{cy:.1f}-h/2+{0.045 * H:.1f}*sin(4*PI*t/{p})"
    if motion == "across":                   # across the screen at its height, again and again
        return "", f"-w+mod(t,{p})/{p}*(W+w)", f"{cy:.1f}-h/2+{0.012 * H:.1f}*sin(2*PI*t/{p / 4:.2f})"
    return "", *still


def sprites(touches, w, h, style, folder, duration):
    """Moving items -> [{"png", "pre", "x", "y", "start", "end"}] for media.burn."""
    from PIL import Image
    folder = Path(folder)
    s = merged(style)
    out = []
    for i, t in enumerate(touches):
        if t.get("motion") not in MOTIONS:
            continue
        blk = touch_block(t, w, h, s)
        if not blk:
            continue
        full = folder / f"move_{i}_full.png"
        renderer.render(full, w, h, [blk])
        im = Image.open(full)
        box = im.getbbox()
        if not box:
            continue
        pad = 4
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(w, box[2] + pad), min(h, box[3] + pad))
        png = folder / f"move_{i}.png"
        im.crop(box).save(png)
        full.unlink()
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        pre, x, y = motion_filters(t["motion"], t.get("period"), cx, cy, w, h)
        start, end = (0.0, duration) if t.get("whole") else (t["start"], t["end"])
        out.append({"png": str(png), "pre": pre, "x": x, "y": y, "start": start, "end": end})
    return out
