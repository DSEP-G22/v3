FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27"
COPY services/orchestrator/app app
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
