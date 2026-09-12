# Stage 1: export the LFS .pt checkpoint to ONNX. Torch lives only here.
FROM python:3.12-slim AS export
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
 && pip install --no-cache-dir onnx
COPY models/router_efficientnet_b0_finetuned.pt models/export_router_onnx.py /src/
RUN python /src/export_router_onnx.py /src/router_efficientnet_b0_finetuned.pt /models

# Stage 2: runtime, onnxruntime only (~16 MB model).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
RUN uv pip install --system --no-cache "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" \
    "numpy>=1.26" "pillow>=10" "onnxruntime>=1.18"
COPY --from=export /models /models
ENV MODEL_DIR=/models OMP_NUM_THREADS=1
COPY services/image/app app
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD python -c "import urllib.request,json;assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['status']=='ok'"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
