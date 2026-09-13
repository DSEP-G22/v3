FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv
WORKDIR /srv
COPY packages/common packages/common
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --system ./packages/common
COPY services/migrate/app app
COPY infra/timescale/schema.sql app/timescale.sql
CMD ["python", "-m", "app"]
