# AutoTransForThai_TraditionalChinese

A quick web tool that downloads a Thai video (or takes one you drop in) and writes Traditional Chinese captions. The app itself is called **AutoCaption**: Thai video in, Traditional Chinese captions out. It runs on your Mac and opens in the browser.

1. **Drop a video** on the page or **paste a link** (YouTube, Bilibili, X, TikTok…).
2. Optionally **give it help**: screenshots of CapCut's caption list, an `.srt`, or someone else's translation (pictures or text). You can also say who's in the video.
3. It **listens** for the Thai (Whisper, on your Mac), **tidies** the Thai, **translates** it, then **checks its own work**. Lines it wasn't sure about get listened to again, once with the music taken away, and fixed without asking you.
4. You watch the video next to the captions. **Flag** anything wrong (⚑: wrong words, translation, timing, or other) and say what's wrong in a few words. Then press **Fix flagged lines**.
5. Something skipped, or a whole part wrong? Press **Fix a stretch…**, mark **From here** and **To here**, and say what's wrong. It listens to just that part again several ways (Thai, any language, another model, the voice with the music removed) and rewrites those lines. Or press **+ Caption at …** and type one yourself.
6. It learns from your notes: names, words and style rules go into **What it has learned** and are used for every video after that. You can edit that list yourself.
7. **Caption style**: pick a theme (經典白, 字幕黃, 黑底框, 奶茶, 粉嫩, 手寫, 娃娃, 夜空) or set the Chinese and Thai fonts, size, colours, outline, shadow, a dark box, and where the captions sit (bottom, top, or drag them). The preview on the video matches what gets burned in.
8. **Emoji and notes**: add (臉紅)💗, (偷笑)🤭, a name tag… at any moment and drag it where you want, or **Let Claude suggest some**: it looks at frames from the video and the captions and proposes touches for you to keep or remove.
9. **Save**: SRT files (Thai, Chinese, both) plus, if you like, a copy of the video with the captions, emoji and notes burned in. They go to `~/Movies/AutoCaption/<video title>/`.

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

One video is a small test, so treat the differences as a hint, not a ranking. To score models on your own video, use `tests/bench_listen.py` with a file of subtitles you trust. The turbo models are several times faster but less accurate; tick **Quicker listening** when you start a video to use one.

## Good to know

- **Songs**: lines that are sung lyrics are marked ♪ and not translated. Type your own if you want them.
- **Videos that already have subtitles burned in** (iQIYI and so on): set **Where** to **Top** in Caption style so the two don't overlap.
- **Models** (top right): choose which model listens and which Claude model tidies, translates, checks and fixes. See [Choosing a listening model](#choosing-a-listening-model).
- **Music or crowd under the talking**: tick that box when you start. It takes away the music before listening, which costs a few minutes but helps a lot with fancams and variety shows.
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
| `ac/models.py` | The listening and Claude models you can pick; converts Thai-tuned Whisper models to MLX the first time |
| `ac/brain.py` | All Claude prompts: read screenshots, tidy, translate, self-check, fix, and draw lessons from your notes |
| `ac/memory.py` | What it has learned (`work/memory.json`) |
| `ac/jobs.py` | The steps, run in the background, with progress in `job.json` |
| `web/` | The page (plain HTML/CSS/JS) |

Tests: `.venv/bin/python -m unittest` (no models, network or Claude needed).
