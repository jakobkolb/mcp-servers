FROM python:3.12-slim

WORKDIR /app

# lp/lpstat/cancel only: CUPS itself runs on the host and is reached via CUPS_SERVER.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

# The chart mounts the host's /run/cups here. The Gotenberg sidecar renders the
# documents and listens on the pod's loopback only.
ENV CUPS_SERVER=/run/cups/cups.sock \
    PRINT_RENDERER_URL=http://127.0.0.1:3000

CMD ["uv", "run", "mcp-print"]
