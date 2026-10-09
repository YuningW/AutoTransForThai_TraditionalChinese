# AutoTransForThai_TraditionalChinese

**AutoCaption** turns a Thai video into Traditional Chinese captions (Taiwan usage). Drop in a video or paste a link. It listens for the Thai, translates it, checks its own work, and gives you an SRT file or a copy of the video with the captions burned in. It runs on your Mac and opens in the browser. Translation goes through your Claude subscription.

## What it does

- **Listens to Thai on your Mac** with a Thai-tuned Whisper model, then Claude tidies the Thai and translates it.
- **Checks itself**: lines it isn't sure about are listened to again, with the music taken out, and fixed without asking you.
- **Uses help when there is some**: the video's own subtitles (YouTube CC, or subtitles burned into the picture), CapCut screenshots, or someone else's translation.
- **Learns from your corrections**: names, words and style rules you teach it are used for every video after that.
- **Lets you fix anything**: edit any line, flag a line and say what's wrong, re-listen to a stretch that was skipped, or add a caption yourself.
- **Styles the captions**: themes, free Chinese fonts, colours, a box, and where they sit. Each line can also have its own size, colour or place.
- **Colours each person**: Milk in one colour, Love in another. It can learn their voices and colour lines automatically.
- **Adds touches**: emoji and little notes like (臉紅)💗, your own text, and your logo, which can float, flip or fly across.
- **Saves** SRT files (Thai, Chinese, or both) and a burned-in video.

## Start

Double-click `AutoCaption.command`. The first run sets everything up in a few minutes, then opens <http://127.0.0.1:8771>.

You need:
- an Apple Silicon Mac
- [Homebrew](https://brew.sh) (setup uses it to install ffmpeg and Python)
- [Claude Code](https://claude.com/claude-code), signed in once (no API key needed)
- Xcode's command-line tools: `xcode-select --install`

The first video also downloads the listening model (about 3 GB) and converts it for the Mac's GPU. That happens once.

## More

| | |
| --- | --- |
| [How to use it](docs/GUIDE.md) | Every feature, step by step, plus tips |
| [Models and test results](docs/MODELS.md) | Which listening and Claude models to pick, accuracy and speed |
| [How it works](docs/HOW-IT-WORKS.md) | What happens to a video, which file does what, and tests |
