# RailInfo — live departure board pushed to a Pixoo 64.
# Single long-running, port-less outbound client: `python main.py --loop`.
# Target: Synology DS218+ (Intel Celeron J3355) → build for linux/amd64.

# --- builder: resolve the locked dependency set into a self-contained venv ----------
FROM python:3.14-slim AS builder

# uv provides fast, reproducible installs straight from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy deps into the image (not link to the cache) and pre-compile to .pyc for faster start.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first, from just the manifest + lockfile, so this layer is cached
# until the dependencies actually change. --no-install-project: RailInfo runs from source
# (main.py imports the `railinfo` package by path), so we never build it as a wheel.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- runtime: slim image carrying only the venv, the source, and the font ------------
FROM python:3.14-slim

# tzdata so TZ (e.g. Europe/London) resolves — the board clock uses local time, and slim
# images ship without it (datetime would otherwise fall back to UTC).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user; the app only needs outbound network, no root.
RUN useradd --create-home --uid 10001 railinfo

# Flush stdout immediately so `docker logs` / Container Manager show events in real time.
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY railinfo/ ./railinfo/
COPY Fonts/ ./Fonts/
COPY main.py ./

USER railinfo

# Station, API keys, PIXOO_HOST and TZ all come from the environment at runtime
# (see docker-compose.yml). --loop streams until SIGTERM (handled gracefully).
CMD ["python", "main.py", "--loop"]
