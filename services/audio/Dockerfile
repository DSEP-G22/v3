FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "httpx>=0.27" "numpy>=1.26" "faster-whisper>=1.0"
# Baked in its own layer so code changes do not re-download ~500 MB of weights.
ENV MODEL_DIR=/models WHISPER_MODEL=small OMP_NUM_THREADS=4
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/models/whisper')"
ENV HF_HUB_OFFLINE=1
COPY services/audio/app app
HEALTHCHECK --interval=10s --timeout=5s --retries=60 CMD python -c "import urllib.request,json;assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['status']=='ok'"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
