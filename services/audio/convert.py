"""Build step: a Hugging Face Whisper fine-tune to CTranslate2 int8, for faster-whisper.

    python convert.py <repo> <revision> <output dir>

Runs in the audio image's conversion stage (torch lives only there). The int8 weights are a
quarter of the float32 checkpoint and decode at the same speed as the base model on CPU. A LoRA
adapter repo (adapter_config.json, no weights of its own) is merged into its base model first, so
it converts like a full fine-tune.
"""

import json
import shutil
import sys
from pathlib import Path

from ctranslate2.converters import TransformersConverter
from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download
from transformers import WhisperForConditionalGeneration, WhisperTokenizerFast

repo, rev, out = sys.argv[1:4]
files = list_repo_files(repo, revision=rev)
if "adapter_config.json" in files:
    from peft import PeftModel

    adapter = snapshot_download(repo, revision=rev)
    base_id = json.loads(Path(adapter, "adapter_config.json").read_text())["base_model_name_or_path"]
    src = "/tmp/merged"
    PeftModel.from_pretrained(WhisperForConditionalGeneration.from_pretrained(base_id), adapter) \
        .merge_and_unload().save_pretrained(src)
    for f in Path(adapter).glob("*"):  # the adapter's own tokenizer files, not its weights or reports
        if f.suffix in (".json", ".txt") and not f.name.startswith(("adapter_", "test_", "training_", "pipeline_")):
            shutil.copy(f, src)
else:
    # Older fine-tunes (vasista22) ship only pytorch_model.bin; never fetch both copies.
    weights = "model.safetensors" if "model.safetensors" in files else "pytorch_model.bin"
    src = snapshot_download(repo, revision=rev, allow_patterns=["*.json", "*.txt", weights],
                            ignore_patterns=["checkpoint-*/*"])
if not Path(src, "preprocessor_config.json").exists():
    shutil.copy(hf_hub_download("openai/whisper-small", "preprocessor_config.json"), src)
WhisperTokenizerFast.from_pretrained(src).save_pretrained(src)  # faster-whisper reads tokenizer.json
TransformersConverter(src, copy_files=["tokenizer.json", "preprocessor_config.json"]).convert(out, quantization="int8", force=True)
print("converted", repo, "to", out)
