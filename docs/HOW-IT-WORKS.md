# How it works

[Back to the README](../README.md)

## Why it can hear when the Claude app can't

Claude reads text and pictures, not sound. Here, Whisper does the listening on your Mac and passes Claude the words, with the parts it wasn't sure about marked. Claude never pretends to hear. When a line is doubtful, Whisper listens again, once with the music removed and once with a looser setting. Claude then picks the reading that fits the conversation, your notes and what it has learned.

## What happens to a video

1. **Download or copy** the video. Separately, download any caption tracks written by people.
2. **Read the video's own subtitles** (caption tracks, and burned-in subtitles via macOS Vision), alongside the listening.
3. **Remove the music** if you asked for it (Demucs).
4. **Listen**: Silero VAD finds speech, and the Whisper model listens in pieces of up to 12 seconds. Lines are cut at Thai word boundaries (PyThaiNLP) and on real pauses.
5. **Tidy the Thai** with Claude, using your helpers and what it has learned. Lines holding two speakers are split.
6. **Translate** into Traditional Chinese (Taiwan usage).
7. **Self-check**: Claude reviews everything. Doubtful lines are listened to again with the best model and fixed.
8. **Fill in** talking the video's subtitles show but the captions missed (only when that option is on).
9. **Line up the timing**: a Thai speech model (wav2vec2) finds where each line's own letters are spoken (forced alignment), so every line starts and ends with its words. Lines you timed yourself are left alone.
10. **Colour** lines by remembered voices.

Captions are always timed to the audio. Subtitles from elsewhere only help with the words and meaning.

## Files

| File | Job |
| --- | --- |
| `ac/jobs.py` | The steps above, run in the background, with progress in `job.json` |
| `ac/listen.py` | Silero VAD finds speech, then mlx-whisper listens to just those parts |
| `ac/relisten.py` | Listens again to short clips of unsure or flagged lines |
| `ac/voice.py` | Demucs takes the music away from the voices |
| `ac/voices.py` | Speaker voiceprints (SpeechBrain ECAPA) for colouring people |
| `ac/align.py` | Forced alignment: each line's timing from where its letters are heard |
| `ac/captions.py` | Cuts lines (never inside a Thai word) and writes SRT |
| `ac/brain.py` | All Claude prompts (through `claude -p`), and a count of the tokens each video uses |
| `ac/memory.py` | What it has learned (`work/memory.json`) |
| `ac/models.py` | The listening and Claude models; converts Thai-tuned Whisper models to MLX the first time |
| `ac/vsubs.py`, `ac/ocr.swift` | The video's own caption tracks and burned-in subtitles, turned into timed help |
| `ac/style.py`, `ac/render.swift` | Caption themes, fonts and per-line looks. Draws each screen with macOS's own text engine (every installed font, colour emoji, proper Thai); ffmpeg lays it over the video |
| `ac/fetch.py` | Downloads videos and caption tracks (yt-dlp) |
| `ac/server.py` | The local web server (only answers this Mac) |
| `web/` | The page (plain HTML, CSS and JavaScript) |

## Fonts in the preview

Safari only lets web pages use the fonts every Mac ships with. So the app serves the free fonts, and the Mac's extra Chinese fonts (圓體, 娃娃體, 楷體…), to the page itself. That way the preview shows the same font as the saved video.

## Tests

```
.venv/bin/python -m unittest
```

These need no models, network or Claude. `tests/ui_flow.py` drives the page in headless Chrome. `tests/bench_listen.py` scores listening models against subtitles you trust.
