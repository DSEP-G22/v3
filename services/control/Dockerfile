FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN uv pip install --system --no-cache ./packages/common "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "httpx>=0.27" "pyyaml>=6"
COPY config config
ENV LANKA_CONFIG_DIR=/srv/config
COPY services/control/app app
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--http", "httptools"]
