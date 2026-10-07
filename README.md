# AutoTransForThai_TraditionalChinese

A quick web tool that downloads a Thai video (or takes one you drop in) and writes Traditional Chinese captions. The app itself is called **AutoCaption**: Thai video in, Traditional Chinese captions out. It runs on your Mac and opens in the browser.

1. **Drop a video** on the page or **paste a link** (YouTube, Bilibili, X, TikTok…).
2. Optionally **give it help**: screenshots of CapCut's caption list, an `.srt`, or someone else's translation (pictures or text). You can also say who's in the video.
3. It **listens** for the Thai (Whisper, on your Mac), **tidies** the Thai, **translates** it, then **checks its own work**. Lines it wasn't sure about get listened to again, once with the music taken away, and fixed without asking you.
4. You watch the video next to the captions. **Flag** anything wrong (⚑: wrong words, translation, timing, or other) and say what's wrong in a few words. Then press **Fix flagged lines**.
5. It learns from your notes: names, words and style rules go into **What it has learned** and are used for every video after that. You can edit that list yourself.
6. **Save**: SRT files (Thai, Chinese, both) plus, if you like, a copy of the video with the captions burned in. They go to `~/Movies/AutoCaption/<video title>/`.

## Start

Double-click `AutoCaption.command`. The first run sets everything up (a few minutes) and opens <http://127.0.0.1:8771>.

It needs:
- an Apple Silicon Mac,
- [Homebrew](https://brew.sh) (setup installs `ffmpeg-full` and Python 3.12),
- [Claude Code](https://claude.com/claude-code), signed in once. Translation goes through your Claude subscription; no API key is needed.

The first video downloads Whisper's large-v3 model (about 3 GB). Music removal reuses VidToAudio's models from `~/Library/Caches/VidToAudio/models`, or downloads them there.

## Why it can hear when the Claude app can't

Claude reads text and pictures, not sound. Here, Whisper does the listening and passes Claude the words, with the parts it wasn't sure about marked. Claude never pretends to hear. When a line is doubtful, Whisper listens again: with the music removed, and with a looser setting. Claude then picks the reading that fits the conversation, your notes and what it has learned.

## Good to know

- **Songs**: lines that are sung lyrics are marked ♪ and not translated. Type your own if you want them.
- **Videos that already have subtitles burned in** (iQIYI and so on): choose **Top** under Save so the two don't overlap.
- **Music or crowd under the talking**: tick that box when you start. It takes away the music before listening, which costs a few minutes but helps a lot with fancams and variety shows.
- Your own typed edits are never overwritten when it redoes or fixes things.
- Everything it works with stays in `work/` (not in git). Delete a video from the list to remove its working files; saved SRT and video files stay.

## Under the hood

| File | Job |
| --- | --- |
| `ac/listen.py` | Silero VAD finds speech, then mlx-whisper (large-v3) listens to just those parts |
| `ac/relisten.py` | Listens again to short clips of unsure or flagged lines |
| `ac/voice.py` | Demucs (htdemucs) takes music away from the voices |
| `ac/captions.py` | Cuts lines (never inside a Thai word, using PyThaiNLP), writes SRT and the ASS file for burning in |
| `ac/brain.py` | All Claude prompts: read screenshots, tidy, translate, self-check, fix, and draw lessons from your notes |
| `ac/memory.py` | What it has learned (`work/memory.json`) |
| `ac/jobs.py` | The steps, run in the background, with progress in `job.json` |
| `web/` | The page (plain HTML/CSS/JS) |

Tests: `.venv/bin/python -m unittest` (no models, network or Claude needed).
