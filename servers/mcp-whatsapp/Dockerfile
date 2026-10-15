# The bridge is pure Go (no CGO), so it cross-compiles natively instead of under QEMU.
FROM --platform=$BUILDPLATFORM golang:1.26-bookworm AS bridge
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY contract/ contract/
COPY internal/ internal/
COPY cmd/whatsapp-bridge/ cmd/whatsapp-bridge/
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w" -o /whatsapp-bridge ./cmd/whatsapp-bridge

FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

COPY --from=bridge /whatsapp-bridge /usr/local/bin/whatsapp-bridge

EXPOSE 8000

# One image, two containers: the chart runs `whatsapp-bridge` as a sidecar sharing
# /store (a PVC) and the pod's loopback with this MCP server.
ENV WHATSAPP_DB_PATH=/store/messages.db \
    WHATSAPP_STORE_DIR=/store

CMD ["uv", "run", "mcp-whatsapp"]
