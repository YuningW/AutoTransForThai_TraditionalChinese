# How to use AutoCaption

[Back to the README](../README.md)

## 1. Start a video

Drop a video file on the page, or paste a link (YouTube, Bilibili, X, TikTok…). Then choose:

- **Remove background music first**: for songs, BGM, fancams or crowd noise. It takes the music out, then listens to the voices. Adds about 10 seconds per minute of video.
- **Quicker listening**: several times faster, but misses more Thai. Best for long videos when a rough first draft is fine.
- **Use subtitles the video already has** (on by default): the video's own caption tracks and subtitles burned into the picture. Only subtitles written by people are used; YouTube's automatic captions are skipped.
  - **Also check the captions against them**: where the subtitles show talking but there's no caption, it listens to that part again and fills it in. It also checks the Thai against their meaning. Worth it with Quicker listening, long videos, or loud music. Adds about a minute per missing part.

All these choices are remembered for next time.

**Give it something to help** (optional): screenshots of CapCut's caption list, an `.srt`, or someone else's translation, as pictures or text. You can also say who's in the video.

When it finishes, **What it did** lists every step, including how many Claude tokens the video used.

## 2. Check and fix the captions

The captions sit next to the video and follow it as it plays. Click a line's time to play from there, or click its text to edit it. Your typed edits are never overwritten.

- **Flag a line** (⚑): pick what's wrong (words, translation, timing, or other), write a few words, then press **Fix flagged lines**.
- **Fix a stretch…**: mark **From here** and **To here** and say what's wrong. It listens to just that part again several ways (Thai, any language, another model, with the music removed) and rewrites those lines.
- **Find skipped talking**: finds talking that has no captions (using the voices, and the video's own subtitles if any) and fills it in.
- **+ Caption at…**: type a caption yourself at the current moment.
- **Timeline** (under the video): the sound wave with every caption as a block. Drag a block to move it, pull its edges to change when it starts or ends, click to jump there. Scroll to move along; ⌘-scroll or pinch to zoom.
- **Split and join**: **S** splits the line at the playhead (the Thai and Chinese are cut at about the same place, never inside a Thai word); **M** joins it with the next line. Both are also under **Aa**.
- **Find and replace**: change a word everywhere at once, for example a name written wrong in 30 lines, in the Chinese, the Thai or both. Tick **Remember it for future videos** to keep it as a rule.
- **Keyboard**: Space plays and pauses, ←/→ move a second (Shift: 5), ↑/↓ go to the previous or next line, **[** and **]** set where the line starts and ends, Enter edits it, F flags it. Press **?** for the full list.
- **Try again**: if something stopped half-way (for example Claude's usage limit), it carries on from that step.

## 3. Make it look right

**Caption style** sets the look for the whole video:
- **Themes**: 經典白, 字幕黃, 黑底框, 奶茶, 粉嫩, 手寫, 娃娃, 粉圓, 文楷, 源泉, 清松, 夜空.
- **Fonts**: the Mac's own Chinese fonts, plus free ones that setup installs: 粉圓, 霞鶩文楷, 芫荽, 辰宇落雁體, 昭源黑體, 思源宋體, 仙人掌明體, 源泉圓體, 昭源圓體, 清松手寫體, 霞鶩漫黑, 朱古力黑體, 滑油字, 俐方體11號.
- **The rest**: size, colours, outline, shadow, a dark box, and where the captions sit (bottom, top, or drag them).

The preview on the video matches what gets burned in.

**One line only**: press **Aa** on a line to give just that line its own:
- position: top, bottom, or drag that caption on the video
- size, colour or bold
- language: Chinese only, Thai only, or hidden
- timing

Use it when a caption covers something on screen, or for a line that deserves to be bigger. Tick other lines and press **Use this look on the ticked lines** to copy it.

## 4. People and colours

Under **Caption style → People**, give each person a colour (Milk 🟡, Love 🔵…).

- **Assign**: pick who says a line with the chip on it, or tick many lines (Shift-click ticks a range) and assign them at once.
- **Two people at once**: on a line, adds a line for the other person. Each gets their own row, in their own colour.
- **Recognise voices**: give each person 3–5 lines yourself, then press it. It learns their voices on your Mac (no Claude usage) and colours the lines that clearly sound like them. The voices are remembered, so later videos are coloured automatically.
- **Let Claude guess from the words**: for example someone says their own name, or is called พี่มิ้ลค์. Guesses have a dashed chip until you change them.

Your usual people are remembered for new videos.

## 5. Emoji, notes, text and logo

- **Emoji and notes**: add (臉紅)💗, (偷笑)🤭 or a name tag at any moment, then drag it where you want. Or press **Let Claude suggest some**: it looks at frames and captions and proposes touches for you to keep or remove.
- **Text and logo**: add a title or credit line (中字 by @you), or your logo from a picture. Set the font, colours, outline, size and transparency. Put it in a corner or drag it, and show it for the whole video or just part of it. Logos are kept for the next video.
- **Making logos stand out**: give a logo an outline, soft shadow, badge or circle. The colour is picked to contrast with the logo.
- **Movement**: anything can float, wiggle, flip, pulse, spin, fly around or fly across, at the speed you choose.

## 6. Save

**Save** writes SRT files (Thai, Chinese, and both) and, if you like, a copy of the video with captions, emoji, notes, text and logo burned in. They go to `~/Movies/AutoCaption/<video title>/`.

**Shape → Vertical 9:16** makes a 1080×1920 copy for Reels, TikTok and Shorts:
- **Fill the screen, cut the sides**: drag the frame on the video to choose which part stays.
- **Whole picture, blurred behind**: keeps all of it, in the middle.

Captions sit higher, clear of the app's buttons, and your text, emoji and logo follow the picture. Your choice is remembered for that video.

## What it learns

Notes on flagged lines teach it names, words and style rules. They go into **What it has learned** (top right), which you can edit, and are used for every video after that. People and their voices are listed there too.

## Tips

- **Videos that already have subtitles burned in** (iQIYI and so on): set **Where** to **Top** so the two don't overlap. Or use **Aa** on single lines.
- **Songs**: sung lyrics are marked ♪ and not translated. Type your own if you want them.
- **Started without removing the music?** Press **Listen again with the music removed** on the video's page. Lines you typed, or fixed with a note, are kept.
- **Long video with English CC written by people?** Quicker listening plus **Also check the captions against them** is a good mix.
- **Working files** stay in `work/`, which isn't in git. Deleting a video from the list removes them; saved SRT and video files stay.
