# Stage 1: the fine-tunes to CTranslate2 int8 (convert.py). Torch lives only here. Research and
# benchmarks behind each: docs/SINHALA-ASR.md and docs/TAMIL-ASR.md.
FROM python:3.12-slim AS si-convert
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch  && pip install --no-cache-dir "transformers>=4.45,<5" "ctranslate2>=4.5,<5" "huggingface_hub>=0.25" "peft>=0.11"
COPY services/audio/convert.py /convert.py
# SinhaSpeech run11 (formerly Yohan2003/whisper-small-sinhala-run11-v6-e6; same weights). Pinned at
# b51781e: later revisions only edit the card but ship a transformers 5 tokenizer config.
RUN python /convert.py SinhaSpeech/whisper-small-sinhala-v6-e6-run11-best b51781e05fce8c67c6dc4c6f5e2a1963ec328344 /out/si-run11-int8
# dehanns LoRA r32 seed 456, merged into whisper-small: the alternative on the speech binding.
RUN python /convert.py dehanns/whisper-small-sinhala-lora-r32-seed-456 3d1a45410e15a4bdf99ab95da82282240187b7e8 /out/si-dehanns-lora-int8
# vasista22/whisper-tamil-small (pinned), the Tamil default (docs/TAMIL-ASR.md):
RUN python /convert.py vasista22/whisper-tamil-small ac0d71cd70d4c66aec7126996cd9e56e97e698b7 /out/ta-vasista22-int8

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "httpx>=0.27" "numpy>=1.26" "faster-whisper==1.2.1" "av>=11,<19"
# av 19 dropped an argument faster-whisper 1.2.1 passes when decoding, so every voice note failed.
# Baked in its own layer so code changes do not re-download ~500 MB of weights.
ENV MODEL_DIR=/models WHISPER_MODEL=small OMP_NUM_THREADS=4
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/models/whisper')"
# The Sinhala models the speech binding can swap between (app/main.py SINHALA_MODELS).
# janiduchamika 185k (float16, ~480 MB, twice run11's error rate) is no longer baked: the VPS
# disk only holds models that earn their place.
# Yohan2003 run11 (test CER 4.4%), the default, converted in stage 1:
COPY --from=si-convert /out/si-run11-int8 /models/whisper/si-run11-int8
COPY --from=si-convert /out/si-dehanns-lora-int8 /models/whisper/si-dehanns-lora-int8
# vasista22 Tamil, converted in stage 1; the speech_ta binding swaps it:
COPY --from=si-convert /out/ta-vasista22-int8 /models/whisper/ta-vasista22-int8
ENV HF_HUB_OFFLINE=1
COPY services/audio/app app
HEALTHCHECK --interval=10s --timeout=5s --retries=60 CMD python -c "import urllib.request,json;assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['status']=='ok'"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
