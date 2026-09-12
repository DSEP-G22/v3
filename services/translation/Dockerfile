# Stage 1: convert NLLB-200 distilled 600M to CTranslate2 int8. Torch lives only here.
FROM python:3.12-slim AS convert
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir "ctranslate2>=4.4" "transformers>=4.44" sentencepiece
ARG NLLB_MODEL=facebook/nllb-200-distilled-600M
RUN ct2-transformers-converter --model ${NLLB_MODEL} --quantization int8 \
      --output_dir /models/nllb-600m-ct2 --copy_files tokenizer.json tokenizer_config.json \
      special_tokens_map.json sentencepiece.bpe.model

# Stage 2: runtime. No torch. MODEL_DIR can point at a volume to override the baked weights.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN uv pip install --system --no-cache ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "ctranslate2>=4.4" "transformers>=4.44" "sentencepiece>=0.2" "deep-translator>=1.11"
COPY --from=convert /models /models
ENV MODEL_DIR=/models OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1
COPY services/translation/app app
HEALTHCHECK --interval=10s --timeout=5s --retries=60 CMD python -c "import urllib.request,json;assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['status']=='ok'"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
