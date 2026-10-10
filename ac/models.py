"""Which models do the listening and the translating, and getting them ready.

Listening models are Whisper variants. Thai-tuned ones are published in Hugging Face's
format; ensure() converts them once to MLX (the Mac GPU format) and keeps them in
~/Library/Caches/AutoCaption/models.
"""
import json
import os
import shutil
import threading
from pathlib import Path

from . import paths

CACHE = Path(os.environ.get("AC_MODELS", Path.home() / "Library/Caches/AutoCaption/models"))

# key -> where it comes from. "mlx": ready-made MLX weights. "hf": converted on first use.
LISTEN = {
    "whisper-large-v3": {"label": "Whisper large-v3 (OpenAI)", "mlx": "mlx-community/whisper-large-v3-mlx",
                         "about": "OpenAI's general model. On our Thai test: 85.8% right, missed 7 of 96 lines."},
    "whisper-turbo": {"label": "Whisper turbo (OpenAI)", "mlx": "mlx-community/whisper-large-v3-turbo",
                      "about": "Fast but weakest on Thai: 74.1% right, missed 14 of 96 on our test."},
    "typhoon-large-v3": {"label": "Typhoon Whisper large-v3 (Thai)", "hf": "typhoon-ai/typhoon-whisper-large-v3",
                         "about": "Whisper retrained on Thai by Typhoon (SCB 10X). On our Thai test: 87.2% right, missed 6 of 96."},
    "typhoon-turbo": {"label": "Typhoon Whisper turbo (Thai)", "hf": "typhoon-ai/typhoon-whisper-turbo",
                      "about": "Thai-trained and fast; used for Quicker listening. On our Thai test: 82.0% right, missed 12 of 96."},
    "thonburian-large-v3": {"label": "Thonburian Whisper large-v3 (Thai)", "hf": "biodatlab/whisper-th-large-v3-combined",
                            "about": "Whisper retrained on Thai by Mahidol University's biodatlab. On our Thai test: 88.7% right, missed 6 of 96, slow."},
    "pathumma-large-v3": {"label": "Pathumma Whisper large-v3 (Thai)", "hf": "nectec/Pathumma-whisper-th-large-v3",
                          "about": "Whisper retrained on Thai by NECTEC. Best on our Thai test: 89.0% right, missed 3 of 96. The default."},
}

# Claude models for tidying, translating, checking and fixing (through the Claude Code CLI)
CLAUDE = {
    "claude-opus-5-5": {"label": "Claude Opus 5.5", "about": "Best translations. The default."},
    "claude-fable-5-1": {"label": "Claude Fable 5.1", "about": "Anthropic's most capable model; slower and uses more of your plan."},
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5", "about": "Faster, nearly as good."},
    "claude-haiku-4-5": {"label": "Claude Haiku 4.5", "about": "Fastest; simpler wording, more mistakes."},
}


def mlx_path(key):
    """Something mlx_whisper.transcribe(path_or_hf_repo=...) accepts, converting first if needed."""
    m = LISTEN.get(key) or LISTEN["whisper-large-v3"]
    if "mlx" in m:
        return m["mlx"]
    out = CACHE / key
    if (out / "config.json").exists() and (out / "weights.safetensors").exists():
        if "quantization" not in json.loads((out / "config.json").read_text()):
            quantize(out)                      # converted before 8-bit was the default
        return str(out)
    convert(m["hf"], out)
    quantize(out)
    return str(out)


def quantize(folder, bits=8):
    """8-bit weights: same score on the Thai test as 16-bit, faster, half the size. 4-bit lost accuracy."""
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_flatten
    from mlx_whisper.load_models import load_model
    folder = Path(folder)
    m = load_model(str(folder), dtype=mx.float16)
    nn.quantize(m, group_size=64, bits=bits)
    tmp = folder.with_name(folder.name + ".q")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    mx.save_safetensors(str(tmp / "weights.safetensors"), dict(tree_flatten(m.parameters())))
    cfg = json.loads((folder / "config.json").read_text())
    cfg["quantization"] = {"group_size": 64, "bits": bits}
    (tmp / "config.json").write_text(json.dumps(cfg, indent=1))
    shutil.rmtree(folder)
    tmp.rename(folder)


def split_at_pauses(key):
    """Thai-tuned (converted) models don't time phrases inside a chunk; listen to each pause-to-pause stretch."""
    return "hf" in LISTEN.get(key, {})


def is_ready(key):
    m = LISTEN.get(key)
    if not m:
        return False
    if "mlx" in m:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(m["mlx"], "config.json"), str)
    f = CACHE / key / "config.json"
    return f.exists() and "quantization" in f.read_text() and (CACHE / key / "weights.safetensors").exists()


def _rename(k):
    """Hugging Face Whisper weight name -> mlx_whisper's (OpenAI-style) name, or None to drop it."""
    if k.startswith("proj_out."):
        return None                                 # tied to the token embedding
    k = k.removeprefix("model.")
    if k == "encoder.embed_positions.weight":
        return None                                 # mlx_whisper computes the encoder's sinusoids
    k = k.replace("encoder.layer_norm.", "encoder.ln_post.")
    k = k.replace("decoder.layer_norm.", "decoder.ln.")
    k = k.replace("decoder.embed_tokens.", "decoder.token_embedding.")
    k = k.replace("decoder.embed_positions.weight", "decoder.positional_embedding")
    k = k.replace(".layers.", ".blocks.")
    for a, b in ((".self_attn.", ".attn."), (".encoder_attn.", ".cross_attn."),
                 (".q_proj.", ".query."), (".k_proj.", ".key."), (".v_proj.", ".value."), (".out_proj.", ".out."),
                 (".self_attn_layer_norm.", ".attn_ln."), (".encoder_attn_layer_norm.", ".cross_attn_ln."),
                 (".final_layer_norm.", ".mlp_ln."), (".fc1.", ".mlp1."), (".fc2.", ".mlp2.")):
        k = k.replace(a, b)
    return k


def convert(repo, out, on_progress=None):
    import mlx.core as mx
    from huggingface_hub import snapshot_download
    src = Path(snapshot_download(repo, allow_patterns=["*.json", "*.safetensors"]))
    cfg = json.loads((src / "config.json").read_text())
    dims = {"n_mels": cfg["num_mel_bins"], "n_audio_ctx": cfg["max_source_positions"],
            "n_audio_state": cfg["d_model"], "n_audio_head": cfg["encoder_attention_heads"],
            "n_audio_layer": cfg["encoder_layers"], "n_vocab": cfg["vocab_size"],
            "n_text_ctx": cfg["max_target_positions"], "n_text_state": cfg["d_model"],
            "n_text_head": cfg["decoder_attention_heads"], "n_text_layer": cfg["decoder_layers"]}
    weights = {}
    for f in sorted(src.glob("*.safetensors")):
        for k, v in mx.load(str(f)).items():
            name = _rename(k)
            if name is None:
                continue
            if name.endswith("conv1.weight") or name.endswith("conv2.weight"):
                v = v.transpose(0, 2, 1)            # PyTorch (out, in, k) -> MLX (out, k, in)
            weights[name] = v.astype(mx.float16)
    # word timings use the base model's alignment heads (fine-tuning keeps them in place)
    base = "mlx-community/whisper-large-v3-turbo" if dims["n_text_layer"] == 4 else "mlx-community/whisper-large-v3-mlx"
    bsrc = Path(snapshot_download(base))
    bw = mx.load(str(next(bsrc.glob("weights.*"))))
    if "alignment_heads" in bw:
        weights["alignment_heads"] = bw["alignment_heads"]
    missing = set(k for k in bw if k != "alignment_heads") - set(weights)
    if missing:
        raise RuntimeError(f"Converting {repo}: {len(missing)} weights missing, e.g. {sorted(missing)[:3]}")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    mx.save_safetensors(str(tmp / "weights.safetensors"), weights)
    (tmp / "config.json").write_text(json.dumps({**dims, "model_type": "whisper"}, indent=1))
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)


# How hard Claude thinks. "auto": deeper for translating, fixing and touches, lighter for tidying and checking.
EFFORTS = {
    "auto": {"label": "Auto", "about": "Thinks harder where it matters (translating, fixing), lighter elsewhere. Recommended."},
    "low": {"label": "Low", "about": "Fastest, uses the least of your plan; more slips in wording."},
    "medium": {"label": "Medium", "about": "Quicker than Auto for everyday clips."},
    "high": {"label": "High", "about": "Every step thinks carefully."},
    "xhigh": {"label": "Extra high", "about": "Slower; for tricky dialogue, slang, wordplay."},
    "max": {"label": "Max", "about": "Slowest and uses the most of your plan."},
}
QUICK = "typhoon-turbo"


# One fix can use its own Claude model and effort (chosen in Fix a stretch / Fix flagged lines): set for the
# job's thread with use(), carried into Claude's worker threads by brain._parallel.
_one_run = threading.local()


def use(model=None, effort=None):
    _one_run.model = model if model in CLAUDE else None
    _one_run.effort = effort if effort in EFFORTS else None


def in_use():
    return getattr(_one_run, "model", None), getattr(_one_run, "effort", None)


def claude_effort(step_default=None):
    """The --effort to pass for a step, or None. Haiku 4.5 has no effort setting."""
    if claude_model().startswith("claude-haiku"):
        return None
    e = getattr(_one_run, "effort", None) or paths.load_settings().get("claude_effort") or "auto"
    return step_default if e == "auto" else e


def listen_key():
    return paths.load_settings().get("listen_model") or "pathumma-large-v3"


def claude_model():
    m = getattr(_one_run, "model", None) or paths.load_settings().get("claude_model")
    return m if m in CLAUDE else paths.CLAUDE_MODEL
