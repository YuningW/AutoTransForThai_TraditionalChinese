"""Listen again to short clips (unsure or flagged lines), the model loaded once for all of them.

    python -m ac.relisten <plan.json> <out.json>
plan: [{"wav", "hint", "temperature"}]  ->  out: [text or ""] in the same order.
"""
import json
import sys
import warnings

from . import listen, paths


def main():
    warnings.filterwarnings("ignore")
    plan = json.loads(open(sys.argv[1]).read())
    try:
        import mlx_whisper
        out = []
        for i, p in enumerate(plan):
            audio = listen.load_wav(p["wav"])
            t = float(p.get("temperature") or 0)
            r = mlx_whisper.transcribe(audio, path_or_hf_repo=paths.WHISPER, language="th", task="transcribe",
                                       verbose=None, temperature=(t, min(1.0, t + 0.3)),
                                       condition_on_previous_text=False, initial_prompt=p.get("hint") or None)
            text = " ".join(s["text"].strip() for s in r.get("segments", [])
                            if s.get("text", "").strip() and not listen._junk(s, s["text"].strip()))
            out.append(text.strip())
            listen.say(progress=round((i + 1) / len(plan), 3))
        with open(sys.argv[2], "w") as f:
            json.dump(out, f, ensure_ascii=False)
        listen.say(done=len(out))
    except Exception as e:
        listen.say(error=str(e) or e.__class__.__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
