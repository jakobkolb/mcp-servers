# Build context is the repository root:  docker build -f servers/mcp-whatsapp/Dockerfile .
# The bridge is pure Go (no CGO), so it cross-compiles natively instead of under QEMU.
FROM --platform=$BUILDPLATFORM golang:1.26-bookworm AS bridge
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY servers/mcp-whatsapp/go.mod servers/mcp-whatsapp/go.sum ./
RUN go mod download
COPY servers/mcp-whatsapp/contract/ contract/
COPY servers/mcp-whatsapp/internal/ internal/
COPY servers/mcp-whatsapp/cmd/whatsapp-bridge/ cmd/whatsapp-bridge/
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w" -o /whatsapp-bridge ./cmd/whatsapp-bridge

# Dependencies come from the workspace's uv.lock (--frozen), so the image runs what CI tested.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /ws
COPY pyproject.toml uv.lock ./
COPY servers servers
RUN uv sync --frozen --no-dev --no-editable --package mcp-whatsapp

FROM python:3.12-slim
COPY --from=build /app/.venv /app/.venv
COPY --from=bridge /whatsapp-bridge /usr/local/bin/whatsapp-bridge
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000

# One image, two containers: the chart runs `whatsapp-bridge` as a sidecar sharing
# /store (a PVC) and the pod's loopback with this MCP server.
ENV WHATSAPP_DB_PATH=/store/messages.db \
    WHATSAPP_STORE_DIR=/store

CMD ["mcp-whatsapp"]
