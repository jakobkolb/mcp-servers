# Build context is the repository root:  docker build -f servers/mcp-obsidian/Dockerfile .
# Dependencies come from the workspace's uv.lock: pinned versions, hash-checked by pip.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
WORKDIR /ws
COPY pyproject.toml uv.lock ./
COPY servers servers
RUN uv export --frozen --no-dev --no-emit-workspace --package mcp-obsidian -o /requirements.txt

# Install binary wheels for the target architecture without running the target
# Python, so the arm64 image is not built under QEMU.
ARG TARGETARCH
RUN case "$TARGETARCH" in \
        arm64) export PIP_PLATFORM="manylinux2014_aarch64" ;; \
        amd64) export PIP_PLATFORM="manylinux2014_x86_64" ;; \
        *) echo "Unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && pip install --no-cache-dir --require-hashes \
        --target /deps \
        --platform "$PIP_PLATFORM" \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        -r /requirements.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /deps /app/deps
COPY servers/mcp-obsidian/src/ /app/src

ENV PYTHONPATH=/app/deps:/app/src
ENV VAULT_PATH=/vault
ENV MCP_TRANSPORT=streamable-http
ENV MCP_PORT=8080
ENV LOG_LEVEL=INFO

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

USER 1000:1000

CMD ["python", "-m", "mcp_obsidian.main"]
