# The TriageModel's frozen MiniLM encoder is the same ONNX export knowledge bakes, so it is
# copied from that image rather than downloaded twice (~90 MB).
ARG MINILM_IMAGE=ghcr.io/dsep-g22/lanka-link-v3-knowledge:latest
FROM ${MINILM_IMAGE} AS minilm

# XLNet priority head (app/xlnet.py), int8 ONNX built by model-testing notebook 08, pinned by checksum.
FROM python:3.12-slim AS xlnet
ADD --checksum=sha256:1666f774f86d80e097b4b789b0a7b8f7191e79e4c15318c5bea58ace282021f1 \
    https://github.com/DSEP-G22/v3/releases/download/model-xlnet-priority-v1/xlnet-priority-int8.tar.gz /xlnet.tgz
RUN mkdir /out && tar xzf /xlnet.tgz -C /out

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "numpy>=1.26" "fastembed>=0.4" "httpx>=0.27" "pydantic>=2.6"
COPY --from=minilm /models /models-cache
ENV MODEL_CACHE_DIR=/models-cache OMP_NUM_THREADS=1 HF_HUB_OFFLINE=1 TRIAGE_MODEL_DIR=/srv/models TRIAGE_LIVE_DIR=/models-live
COPY services/triage/models models
COPY --from=xlnet /out models/xlnet-priority
COPY services/triage/app app
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
