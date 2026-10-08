"""Fast checks that need no model, no network and no Claude:  .venv/bin/python -m unittest"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AC_WORK"] = tempfile.mkdtemp(prefix="ac-test-")

from ac import captions, listen, memory, style  # noqa: E402


def words(*items):
    """items: (word, start, end, p)"""
    return [{"word": w, "start": s, "end": e, "p": p} for w, s, e, p in items]


class Captions(unittest.TestCase):
    def test_breaks_at_pause_not_inside_a_word(self):
        seg = {"start": 0, "end": 4, "text": "", "words": words(
            ("ไม่", 0.0, 0.3, .9), ("รู้", 0.3, 0.6, .9), ("หน้า", 0.6, 0.9, .9), ("ที่", 0.9, 1.2, .9),
            ("หน่", 1.2, 1.4, .9), ("อย", 2.0, 2.2, .9),          # a pause in the middle of หน่อย
            (" ได้", 3.0, 3.3, .9), ("ไหม", 3.3, 3.6, .9))}
        ls = captions.from_segments([seg])
        joined = [l["th"] for l in ls]
        self.assertFalse(any(t.endswith("หน่") for t in joined), joined)
        self.assertIn("หน่อย", "".join(joined))
        self.assertEqual([l["id"] for l in ls], list(range(1, len(ls) + 1)))

    def test_long_piece_without_word_timings_is_cut_at_pauses(self):
        text = "ช่วงนี้ชอบฟังเพลงของเจนนี่ เจนนี่แบล็คพิงค์ ช่วงนี้ชอบฟังเพลงของคนที่ชื่อ นึกชื่อไม่ออก"
        seg = {"start": 40.0, "end": 52.0, "text": text, "avg_logprob": -0.2, "words": [], "gaps": [44.9, 47.5]}
        ls = captions.from_segments([seg])
        self.assertGreater(len(ls), 1)
        self.assertTrue(all(captions.visible_len(l["th"]) <= captions.MAX_CHARS for l in ls))
        self.assertTrue(any(abs(l["end"] - g) < 0.01 for l in ls[:-1] for g in seg["gaps"]), [l["end"] for l in ls])
        self.assertEqual("".join(l["th"] for l in ls).replace(" ", ""), text.replace(" ", ""))

    def test_short_lines_stay_up_long_enough(self):
        seg = {"start": 0, "end": 0.2, "text": "", "words": words(("อ่ะ", 0.0, 0.2, .9))}
        seg2 = {"start": 5, "end": 6, "text": "", "words": words(("ครับ", 5.0, 6.0, .9))}
        ls = captions.from_segments([seg, seg2])
        self.assertGreaterEqual(ls[0]["end"] - ls[0]["start"], captions.MIN_SECONDS)
        self.assertLess(ls[0]["end"], ls[1]["start"])

    def test_srt_round_trip(self):
        ls = [{"id": 1, "start": 1.5, "end": 3.25, "th": "สวัสดี", "zh": "你好"},
              {"id": 2, "start": 61.0, "end": 62.0, "th": "ครับ", "zh": ""}]
        both = captions.srt(ls, "both")
        self.assertIn("00:00:01,500 --> 00:00:03,250\n你好\nสวัสดี", both)
        self.assertEqual(captions.srt(ls, "zh").count("-->"), 1)       # empty Chinese lines are skipped
        back = captions.parse_srt(captions.srt(ls, "th"))
        self.assertEqual([(b["start"], b["end"], b["text"]) for b in back],
                         [(1.5, 3.25, "สวัสดี"), (61.0, 62.0, "ครับ")])



class Style(unittest.TestCase):
    def test_theme_then_your_changes(self):
        st = style.merged({"theme": "pink", "size": 1.4})
        self.assertEqual(st["zh_font"], "Yuanti TC")            # from the theme
        self.assertEqual(st["size"], 1.4)                       # your change wins
        self.assertEqual(style.merged({"theme": "nope"})["zh_font"], style.DEFAULT["zh_font"])

    def test_caption_block_order_and_position(self):
        line = {"th": "สวัสดี", "zh": "你好", "kind": "speech"}
        b = style.caption_block(line, "both", 1920, 1080, style.merged({}))
        self.assertEqual([r["text"] for r in b["rows"]], ["สวัสดี", "你好"])
        self.assertEqual((b["anchor"], b["y"]), ("bottom", 0.94))
        self.assertAlmostEqual(b["rows"][1]["size"], 1080 * 0.058, places=0)
        top = style.caption_block(line, "zh", 1080, 1920, style.merged({"position": "top", "order": "zh_above"}))
        self.assertEqual(([r["text"] for r in top["rows"]], top["anchor"]), (["你好"], "top"))
        self.assertIsNone(style.caption_block({"th": "", "zh": ""}, "both", 1920, 1080, style.merged({})))

    def test_people_talking_at_once_get_own_rows_and_colours(self):
        people = [{"id": "m", "color": "#FFE14D"}, {"id": "l", "color": "#9FD8FF"}]
        a = {"start": 1, "end": 3, "th": "ก", "zh": "甲", "speaker": "l"}
        b = {"start": 0.5, "end": 3, "th": "ข", "zh": "乙", "speaker": "m"}
        blk = style.caption_block([a, b], "zh", 1920, 1080, style.merged({}), people)
        self.assertEqual([(r["text"], r["color"]) for r in blk["rows"]], [("乙", "#FFE14D"), ("甲", "#9FD8FF")])
        # a short line is stretched to be readable, up to the same person's next line, not the other's
        ls = captions.fix_timing([{"start": 1.0, "end": 1.1, "th": "ก", "speaker": "m"},
                                  {"start": 1.05, "end": 2.0, "th": "ข", "speaker": "l"},
                                  {"start": 1.5, "end": 2.5, "th": "ค", "speaker": "m"}])
        self.assertEqual(ls[0]["end"], 1.46)

    def test_logo_block_uses_the_picture(self):
        from ac import paths
        paths.LOGOS.mkdir(parents=True, exist_ok=True)
        (paths.LOGOS / "abcd1234.png").write_bytes(b"png")
        (paths.LOGOS / "abcd1234.json").write_text("{}")        # sorts first; must not be picked
        b = style.touch_block({"kind": "image", "image": "abcd1234", "x": 0.1, "y": 0.9, "w": 0.2, "opacity": 0.5},
                              1920, 1080, style.merged({}))
        self.assertTrue(b["image"].endswith("abcd1234.png"))
        self.assertEqual((b["w"], b["opacity"]), (0.2, 0.5))

    def test_timeline_merges_touches_and_lines(self):
        lines = [{"start": 1, "end": 3, "th": "ก", "zh": "甲"}, {"start": 5, "end": 6, "th": "ข", "zh": ""}]
        touches = [{"start": 2, "end": 5.5, "text": "💗"}]
        spans = style.timeline(lines, touches, "zh")                 # line 2 has no Chinese: not shown
        shown = [(a, b, sorted(k for k, _ in on)) for a, b, on in spans]
        self.assertEqual(shown, [(0.0, 1, []), (1, 2, ["line"]), (2, 3, ["line", "touch"]), (3, 5.5, ["touch"])])


class Voices(unittest.TestCase):
    def test_only_clear_matches_are_coloured(self):
        from ac import voices
        milk, love = voices.unit([1, 0, 0]), voices.unit([0, 1, 0])
        prints = {"milk": milk, "love": love}
        self.assertEqual(voices.match(voices.unit([0.9, 0.2, 0.1]), prints), "milk")
        self.assertIsNone(voices.match(voices.unit([0.6, 0.55, 0.2]), prints))     # too close to call
        self.assertIsNone(voices.match(voices.unit([0.1, 0.1, 1.0]), prints))      # sounds like nobody taught


class Junk(unittest.TestCase):
    def test_whisper_loops_are_dropped(self):
        self.assertTrue(listen._junk({"compression_ratio": 12.0, "avg_logprob": -0.1}, "ฮ."))
        self.assertTrue(listen._junk({"compression_ratio": 1.0, "avg_logprob": -0.7}, "ฮ."))
        self.assertFalse(listen._junk({"compression_ratio": 1.8, "avg_logprob": -0.2}, "ไม่รู้หน้าที่เหรอ"))
        self.assertTrue(listen._junk({"compression_ratio": 3.0, "avg_logprob": -0.1}, "อ่ะ อ่ะ อ่ะ อ่ะ อ่ะ อ่ะ อ่ะ"))
        self.assertTrue(listen._junk({"compression_ratio": 3.0, "avg_logprob": -0.1}, "ก็คือคือคือคือคือคือคือคือ"))

    def test_long_ordinary_thai_is_kept(self):
        # this compresses 2.9:1 like all Thai; the old filter threw it away
        line = "แต่ว่าหนูก็เป็นอย่างนี้มาตั้งแต่เด็กอ่ะก็คือเหมือนอย่างที่บอกตั้งแต่แรก"
        self.assertFalse(listen._junk({"compression_ratio": 2.9, "avg_logprob": -0.03, "no_speech_prob": 0.0}, line))
        self.assertFalse(listen._junk({"compression_ratio": 2.0, "avg_logprob": -0.2}, "น่ารัก น่ารัก"))   # said twice: fine


class Hints(unittest.TestCase):
    def test_only_openai_whisper_gets_the_hint(self):
        from ac import models
        self.assertTrue(listen.takes_hint("mlx-community/whisper-large-v3-mlx"))
        self.assertFalse(listen.takes_hint(str(models.CACHE / "pathumma-large-v3")))


class Memory(unittest.TestCase):
    def setUp(self):
        Path(os.environ["AC_WORK"], "memory.json").unlink(missing_ok=True)
        memory.paths.MEMORY = Path(os.environ["AC_WORK"]) / "memory.json"

    def test_lessons_become_memory_and_prompt_text(self):
        memory.learn([{"type": "name", "th": "มิ้ลค์", "zh": "Milk", "rule": "Milk Pansa"},
                      {"type": "word", "th": "โอ", "zh": "加班", "rule": "OT"},
                      {"type": "style", "rule": "Use 妳 for women"},
                      {"type": "style"}])                            # empty: ignored
        m = memory.load()
        self.assertEqual((len(m["names"]), len(m["words"]), len(m["rules"])), (1, 1, 1))
        memory.learn([{"type": "name", "th": "มิ้ลค์", "zh": "Milk 米可"}])   # same Thai: updated
        self.assertEqual(memory.load()["names"][0]["zh"], "Milk 米可")
        text = memory.prompt_text()
        self.assertIn("มิ้ลค์ → Milk 米可", text)
        self.assertIn("Use 妳 for women", text)
        self.assertNotIn("Use 妳", memory.prompt_text("th"))
        self.assertIn("มิ้ลค์", memory.whisper_hint())

    def test_renaming_someone_keeps_one_person(self):
        memory.remember_people([{"id": "a1", "name": "Love", "color": "#FFE14D"}])
        memory.remember_people([{"id": "b2", "name": "Love", "color": "#9FD8FF"}])   # added again in another video
        memory.remember_people([{"id": "b2", "name": "P'Love", "color": "#9FD8FF"}])  # then renamed there
        people = memory.load()["people"]
        self.assertEqual([(p["name"], p["color"]) for p in people], [("P'Love", "#9FD8FF")])

    def test_remove(self):
        m = memory.add("rules", text="Keep particles")
        rid = m["rules"][0]["id"]
        self.assertEqual(memory.remove("rules", rid)["rules"], [])


if __name__ == "__main__":
    unittest.main()
