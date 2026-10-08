# AutoTransForThai_TraditionalChinese

A quick web tool that downloads a Thai video (or takes one you drop in) and writes Traditional Chinese captions. The app itself is called **AutoCaption**: Thai video in, Traditional Chinese captions out. It runs on your Mac and opens in the browser.

1. **Drop a video** on the page or **paste a link** (YouTube, Bilibili, X, TikTok…).
2. It **uses subtitles the video already has** (on by default): the video's own caption tracks (YouTube CC, or subtitle tracks inside the file), and Thai, English or Chinese subtitles burned into the picture, which it reads from the frames with your Mac's own text recognition. Thai ones help with the Thai, English or Chinese ones with the translation. On a finished video, **Use subtitles already in the video** (Help you gave it) does the same.
3. Optionally **give it help**: screenshots of CapCut's caption list, an `.srt`, or someone else's translation (pictures or text). You can also say who's in the video.
4. It **listens** for the Thai (Whisper, on your Mac), **tidies** the Thai, **translates** it, then **checks its own work**. Lines it wasn't sure about get listened to again, once with the music taken away, and fixed without asking you.
5. You watch the video next to the captions. **Flag** anything wrong (⚑: wrong words, translation, timing, or other) and say what's wrong in a few words. Then press **Fix flagged lines**.
6. Something skipped, or a whole part wrong? Press **Fix a stretch…**, mark **From here** and **To here**, and say what's wrong. It listens to just that part again several ways (Thai, any language, another model, the voice with the music removed) and rewrites those lines. Or press **+ Caption at …** and type one yourself.
7. It learns from your notes: names, words and style rules go into **What it has learned** and are used for every video after that. You can edit that list yourself.
8. **Caption style**: pick a theme (經典白, 字幕黃, 黑底框, 奶茶, 粉嫩, 手寫, 娃娃, 粉圓, 文楷, 夜空) or set the Chinese and Thai fonts (setup also installs free, open-source Chinese fonts: 粉圓 Huninn, 霞鶩文楷 LXGW WenKai, 芫荽 Iansui, 辰宇落雁體, 昭源黑體, 思源宋體, 仙人掌明體), size, colours, outline, shadow, a dark box, and where the captions sit (bottom, top, or drag them). The preview on the video matches what gets burned in.
9. **People and colours**: under Caption style → People, give each person a colour (Milk 🟡, Love 🔵…). Pick who says a line with the chip on it, or tick many lines (Shift-click ticks a range) and assign them at once. When two people talk over each other, press **Two people at once** on a line: each gets their own row, in their own colour. Your usual people are remembered for new videos. **Recognise voices**: give each person 3–5 lines yourself, press it, and it learns their voices on your Mac (no Claude usage), colours the lines that clearly sound like them, and remembers the voices so your next videos are coloured automatically. **Or let Claude guess from the words** (someone says their own name, or is called พี่มิ้ลค์). Guesses have a dashed chip until you change them.
10. **Emoji and notes**: add (臉紅)💗, (偷笑)🤭, a name tag… at any moment and drag it where you want, or **Let Claude suggest some**: it looks at frames from the video and the captions and proposes touches for you to keep or remove.
11. **Text and logo**: add your own text (a title, a credit line like 中字 by @you) or your logo from a picture. Set the font, colours, outline, size and how see-through it is, put it in a corner or drag it, and show it for the whole video or just part. Logos are kept, so you can reuse them on the next video with one click. Logos can have an outline, soft shadow, badge or circle so they stand out on any picture (the colour is picked to contrast with the logo), and anything you add (logo, text, emoji) can move: float, wiggle, flip, pulse, spin, fly around or fly across, at the speed you choose.
12. **Save**: SRT files (Thai, Chinese, both) plus, if you like, a copy of the video with the captions, emoji and notes burned in. They go to `~/Movies/AutoCaption/<video title>/`.

## Start

Double-click `AutoCaption.command`. The first run sets everything up (a few minutes) and opens <http://127.0.0.1:8771>.

It needs:
- an Apple Silicon Mac,
- [Homebrew](https://brew.sh) (setup installs `ffmpeg-full` and Python 3.12),
- [Claude Code](https://claude.com/claude-code), signed in once. Translation goes through your Claude subscription; no API key is needed.
- Xcode's command-line tools (`xcode-select --install`), to build the small caption renderer the first time you save a video.

The first video downloads the listening model (Pathumma Whisper large-v3, about 3 GB) and converts it for the Mac's GPU, a few minutes once. Music removal reuses VidToAudio's models from `~/Library/Caches/VidToAudio/models`, or downloads them there.

## Why it can hear when the Claude app can't

Claude reads text and pictures, not sound. Here, Whisper does the listening and passes Claude the words, with the parts it wasn't sure about marked. Claude never pretends to hear. When a line is doubtful, Whisper listens again: with the music removed, and with a looser setting. Claude then picks the reading that fits the conversation, your notes and what it has learned.

## Choosing a listening model

Under **Models** you can pick which Whisper model listens. Thai-tuned versions of Whisper hear Thai better than OpenAI's original. We scored them on a MilkLove interview against its own official Thai subtitles (96 lines). *Matched* is how much of the official text each model got; *missed* is lines it skipped or badly misheard:

| Model | Matched | Missed | |
| --- | --- | --- | --- |
| [Pathumma Whisper large-v3](https://huggingface.co/nectec/Pathumma-whisper-th-large-v3) (NECTEC) | **89.0%** | **3** | the default |
| [Thonburian Whisper large-v3](https://huggingface.co/biodatlab/whisper-th-large-v3-combined) (biodatlab) | 88.7% | 6 | much slower |
| [Typhoon Whisper large-v3](https://huggingface.co/typhoon-ai/typhoon-whisper-large-v3) (SCB 10X) | 87.2% | 6 | |
| Whisper large-v3 (OpenAI) | 85.8% | 7 | |
| [Typhoon Whisper turbo](https://huggingface.co/typhoon-ai/typhoon-whisper-turbo) | 82.0% | 12 | used for **Quicker listening** |
| Whisper turbo (OpenAI) | 74.1% | 14 | |

One video is a small test, so treat the differences as a hint, not a ranking. To score models on your own video, use `tests/bench_listen.py` with a file of subtitles you trust. The turbo models are faster but skipped whole stretches of talking in this test; tick **Quicker listening** when you start a video to use Typhoon turbo.

With the background music removed first, the scores stayed the same on this interview (its music is quiet), so that option is for clips where music or a crowd is loud.

Thai-tuned models write each piece of speech as one run of text with no usable timing inside it. AutoCaption listens to pieces of up to 12 seconds (joined across pauses under 0.8 s), keeps the models in 8-bit, and skips their word timings; then lines are cut at Thai word boundaries, Claude splits lines that hold two speakers or several short answers, and every cut lands on a real pause in the audio. On the 4-minute interview this listens in about 80 seconds instead of 8–10 minutes, with the same accuracy (89%, 3 of 96 lines missed). A 16-minute video takes roughly 15–20 minutes from start to finished captions.

**Recognising voices** uses SpeechBrain's ECAPA speaker model. On *THE INTERVIEW EP.1* (Girl Rules, six people, 21 minutes), whose English captions name each speaker: after 4 lines per person it coloured 56% of the remaining lines by itself, 96% of them right (Milk vs Love: 90 of 91), and left the short or unclear ones blank. With only remembered voices (nothing assigned) it did the same: 58% coloured, 97% right.

Under **Models** you can also set **how hard Claude thinks**: Auto (deeper for translating and fixing, lighter for tidying), or one level for every step from Low (fastest, uses the least of your plan) to Max.

## Good to know

- **Songs**: lines that are sung lyrics are marked ♪ and not translated. Type your own if you want them.
- **Videos that already have subtitles burned in** (iQIYI and so on): set **Where** to **Top** in Caption style so the two don't overlap.
- **Models** (top right): choose which model listens and which Claude model tidies, translates, checks and fixes. See [Choosing a listening model](#choosing-a-listening-model).
- **Background music**: tick **Remove background music first** when you start (it remembers your choice). It takes the music out, then listens to the voices, which adds about 10 seconds per minute of video. Already started without it? Press **Listen again with the music removed** on the video's page; lines you typed or fixed with a note are kept.
- Your own typed edits are never overwritten when it redoes or fixes things.
- Everything it works with stays in `work/` (not in git). Delete a video from the list to remove its working files; saved SRT and video files stay.

## Under the hood

| File | Job |
| --- | --- |
| `ac/listen.py` | Silero VAD finds speech, then mlx-whisper (large-v3) listens to just those parts |
| `ac/relisten.py` | Listens again to short clips of unsure or flagged lines |
| `ac/voice.py` | Demucs (htdemucs) takes music away from the voices |
| `ac/captions.py` | Cuts lines (never inside a Thai word, using PyThaiNLP) and writes SRT |
| `ac/style.py`, `ac/render.swift` | Caption themes and styles; draws each screen of captions and touches with macOS's own text engine (every installed font, colour emoji, proper Thai), which ffmpeg then lays over the video |
| `ac/vsubs.py`, `ac/ocr.swift` | The video's own caption tracks and its burned-in subtitles (read with macOS Vision), turned into timed help |
| `ac/models.py` | The listening and Claude models you can pick; converts Thai-tuned Whisper models to MLX the first time |
| `ac/brain.py` | All Claude prompts: read screenshots, tidy, translate, self-check, fix, and draw lessons from your notes |
| `ac/memory.py` | What it has learned (`work/memory.json`) |
| `ac/jobs.py` | The steps, run in the background, with progress in `job.json` |
| `web/` | The page (plain HTML/CSS/JS) |

Tests: `.venv/bin/python -m unittest` (no models, network or Claude needed).
