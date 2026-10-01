"""Build step: a Hugging Face Whisper fine-tune to CTranslate2 int8, for faster-whisper.

    python convert.py <repo> <revision> <output dir>

Runs in the audio image's conversion stage (torch lives only there). The int8 weights are a
quarter of the float32 checkpoint and decode at the same speed as the base model on CPU.
"""

import sys

from ctranslate2.converters import TransformersConverter
from huggingface_hub import snapshot_download
from transformers import WhisperTokenizerFast

repo, rev, out = sys.argv[1:4]
src = snapshot_download(repo, revision=rev, allow_patterns=["*.json", "*.txt", "model.safetensors"],
                        ignore_patterns=["checkpoint-*/*"])
WhisperTokenizerFast.from_pretrained(src).save_pretrained(src)  # faster-whisper reads tokenizer.json
TransformersConverter(src, copy_files=["tokenizer.json", "preprocessor_config.json"]).convert(out, quantization="int8", force=True)
print("converted", repo, "to", out)
