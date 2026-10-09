# Models and test results

[Back to the README](../README.md)

Under **Models** (top right) you pick:
- **The listening model**: which Whisper model hears the Thai.
- **The Claude model**: tidies, translates, checks and fixes.
- **How hard Claude thinks**: Auto (deeper for translating and fixing, lighter for tidying), or one level for every step, from Low (fastest, uses the least of your plan) to Max.

## Listening models

Thai-tuned versions of Whisper hear Thai better than OpenAI's original. We scored them on a MilkLove interview against its own official Thai subtitles (96 lines):
- **Matched**: how much of the official text each model got.
- **Missed**: lines it skipped or badly misheard.

| Model | Matched | Missed | |
| --- | --- | --- | --- |
| [Pathumma Whisper large-v3](https://huggingface.co/nectec/Pathumma-whisper-th-large-v3) (NECTEC) | **89.0%** | **3** | the default |
| [Thonburian Whisper large-v3](https://huggingface.co/biodatlab/whisper-th-large-v3-combined) (biodatlab) | 88.7% | 6 | much slower |
| [Typhoon Whisper large-v3](https://huggingface.co/typhoon-ai/typhoon-whisper-large-v3) (SCB 10X) | 87.2% | 6 | |
| Whisper large-v3 (OpenAI) | 85.8% | 7 | |
| [Typhoon Whisper turbo](https://huggingface.co/typhoon-ai/typhoon-whisper-turbo) | 82.0% | 12 | used for **Quicker listening** |
| Whisper turbo (OpenAI) | 74.1% | 14 | |

One video is a small test, so treat the differences as a hint, not a ranking. The turbo models are faster but skipped whole stretches of talking. To score models on your own video, run `tests/bench_listen.py` with a file of subtitles you trust.

## Speed

- **A 4-minute interview** listens in about 80 seconds and takes about 7 minutes in all: listening, then Claude tidying and translating (about 2 minutes), then the self-check (about 4 minutes).
- **A 16-minute video** takes roughly 15–20 minutes from start to finished captions.

## Timing

The Thai-tuned listening models say when a piece of speech (up to about 12 seconds) starts and ends, but not when each word in it is said. So lines cut from one piece used to share its time by text length, and could be a second or more off, up to 5 seconds on long pieces. Now every line is lined up with its own words using [airesearch/wav2vec2-large-xlsr-53-th](https://huggingface.co/airesearch/wav2vec2-large-xlsr-53-th) (about 1.2 GB, downloaded once). On a 6-minute interview, against its human-made Thai subtitles:

| | Typical error | Over 1 s off | Over 2 s off |
| --- | --- | --- | --- |
| Before | 0.47 s | 14 of 53 | 5 |
| Lined up | **0.19 s** | **8** | **1** |

An hour of video takes about a minute and a half.

## Help from the video's own subtitles

On the same interview, using its subtitles as help raised the match from 91.1% to 97.1%, and missed lines fell from 5 to 2.

With **Also check the captions against them** on, English subtitles find talking that was skipped. On a 6-minute test, 30 seconds of captions were removed as if listening had skipped them. The English subtitles found both gaps, and it filled them back in 1 minute 40 seconds, more completely than the first listen. When nothing is missing, it adds almost no time.

## Removing the music

With the background music removed first, the scores stayed the same on this interview, because its music is quiet. The option is for clips where music or a crowd is loud.

## Recognising voices

This uses SpeechBrain's ECAPA speaker model. It was tested on *THE INTERVIEW EP.1* (Girl Rules, six people, 21 minutes), whose English captions name each speaker:
- **After 4 lines per person**, it coloured 56% of the remaining lines by itself, and 96% of those were right. Milk vs Love: 90 of 91 right. Short or unclear lines were left blank.
- **With only remembered voices** (nothing assigned), it did about the same: 58% coloured, 97% right.
