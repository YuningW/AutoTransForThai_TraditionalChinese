"""Fast checks that need no model, no network and no Claude:  .venv/bin/python -m unittest"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["AC_WORK"] = tempfile.mkdtemp(prefix="ac-test-")

from ac import captions, listen, memory  # noqa: E402


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

    def test_ass_keeps_thai_and_chinese_apart(self):
        ls = [{"id": 1, "start": 0, "end": 2, "th": "สวัสดี {x}", "zh": "你好", "kind": "speech"}]
        a = captions.ass(ls, "both", 1920, 1080)
        events = [l for l in a.splitlines() if l.startswith("Dialogue")]
        self.assertEqual(len(events), 2)
        self.assertIn("ZH", events[0])
        th_margin = int(events[1].split(",")[7])
        self.assertGreater(th_margin, 1080 * 0.06)                  # above the Chinese line
        self.assertNotIn("{x}", a)                                    # braces can't inject ASS tags
        top = captions.ass(ls, "zh", 1080, 1920, {"position": "top"})
        self.assertIn(",8,", top.split("Style: ZH", 1)[1].splitlines()[0])


class Junk(unittest.TestCase):
    def test_whisper_loops_are_dropped(self):
        self.assertTrue(listen._junk({"compression_ratio": 12.0, "avg_logprob": -0.1}, "ฮ."))
        self.assertTrue(listen._junk({"compression_ratio": 1.0, "avg_logprob": -0.7}, "ฮ."))
        self.assertFalse(listen._junk({"compression_ratio": 1.8, "avg_logprob": -0.2}, "ไม่รู้หน้าที่เหรอ"))


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

    def test_remove(self):
        m = memory.add("rules", text="Keep particles")
        rid = m["rules"][0]["id"]
        self.assertEqual(memory.remove("rules", rid)["rules"], [])


if __name__ == "__main__":
    unittest.main()
