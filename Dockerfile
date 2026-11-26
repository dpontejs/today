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

# ---- claude: the pinned Claude Code CLI for job analysis (ADR 0007)
FROM node:22-slim AS claude
RUN npm install -g @anthropic-ai/claude-code@2.1.331 && npm cache clean --force

# ---- runtime
FROM python:3.12-slim
# Links the GHCR package to this repo.
LABEL org.opencontainers.image.source="https://github.com/dpontejs/today"
# A home directory: `claude -p` keeps its config under ~/.claude.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir /data && chown app:app /data
# Since 2.x the npm package installs a self-contained native binary: Node itself stays in the build stage.
COPY --from=claude /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/today.db
WORKDIR /app
USER app
# SQLite lives here; mount a volume so items survive new images.
VOLUME /data
EXPOSE 8000
# Each check starts a new interpreter inside the container's cgroup. Importing urllib.request cost ~0.5 s
# of CPU on the VPS, every 10 s: ~95% of this container's CPU. A raw socket under `python -S` (no
# site import) costs ~3.6x less, and the 60 s interval 6x less. Probing every 2 s during the start
# period keeps deploys fast: `docker compose up --wait` and the CI smoke test still see "healthy" in seconds.
HEALTHCHECK --interval=60s --timeout=3s --start-period=30s --start-interval=2s --retries=3 \
  CMD ["python", "-S", "-c", "import socket; s = socket.create_connection(('127.0.0.1', 8000), 2); s.sendall(b'GET /healthz HTTP/1.0\\r\\n\\r\\n'); raise SystemExit(b''.join(iter(lambda: s.recv(4096), b'')).split()[1] != b'200')"]
# Only reachable through Caddy, so the forwarded client IP (used by the login rate limit) is trusted.
CMD ["uvicorn", "today.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
