FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir build

COPY pyproject.toml .
COPY src/ src/

RUN python -m build --wheel --outdir /wheels

ARG TARGETARCH
RUN case "$TARGETARCH" in \
        arm64) export PIP_PLATFORM="manylinux2014_aarch64" ;; \
        amd64) export PIP_PLATFORM="manylinux2014_x86_64" ;; \
        *) echo "Unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && pip install --no-cache-dir \
        --target /deps \
        --platform "$PIP_PLATFORM" \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        /wheels/*.whl


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /deps /app/deps
COPY src/ /app/src

ENV PYTHONPATH=/app/deps:/app/src
ENV VAULT_PATH=/vault
ENV MCP_TRANSPORT=sse
ENV MCP_PORT=8080
ENV LOG_LEVEL=INFO

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

USER 1000:1000

CMD ["python", "-m", "mcp_obsidian.main"]
