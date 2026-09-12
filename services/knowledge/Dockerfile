FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN uv pip install --system --no-cache ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "httpx>=0.27" "numpy>=1.26" "pyyaml>=6" "pydantic>=2.6" "fastembed>=0.4"
# MiniLM-L6 ONNX (~90 MB) baked in its own layer.
ENV MODEL_DIR=/models OMP_NUM_THREADS=1
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/models')"
ENV HF_HUB_OFFLINE=1
COPY config config
ENV LANKA_CONFIG_DIR=/srv/config
COPY services/knowledge/app app
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD python -c "import urllib.request,json;assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['status']=='ok'"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
