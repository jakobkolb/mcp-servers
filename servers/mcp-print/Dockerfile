# Build context is the repository root:  docker build -f servers/mcp-print/Dockerfile .
# Dependencies come from the workspace's uv.lock (--frozen), so the image runs what CI tested.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /ws
COPY pyproject.toml uv.lock ./
COPY servers servers
RUN uv sync --frozen --no-dev --no-editable --package mcp-print

FROM python:3.12-slim
# lp/lpstat/cancel only: CUPS itself runs on the host and is reached via CUPS_SERVER.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000

# The chart mounts the host's /run/cups here. The Gotenberg sidecar renders the
# documents and listens on the pod's loopback only.
ENV CUPS_SERVER=/run/cups/cups.sock \
    PRINT_RENDERER_URL=http://127.0.0.1:3000

# Unprivileged, and a UID no host account uses.
ENV HOME=/tmp
USER 10001:10001

CMD ["mcp-print"]
