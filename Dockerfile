# syntax=docker/dockerfile:1

# ---- build: uv only exists in this stage
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused while only the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime
FROM python:3.12-slim
# Links the GHCR package to this repo.
LABEL org.opencontainers.image.source="https://github.com/dpontejs/today"
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/today.db
WORKDIR /app
USER app
# SQLite lives here; mount a volume so items survive new images.
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
# Only reachable through Caddy, so the forwarded client IP (used by the login rate limit) is trusted.
CMD ["uvicorn", "today.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
