# Build context is the repository root:  docker build -f servers/mcp-whisper/Dockerfile .
# Dependencies come from the workspace's uv.lock (--frozen), so the image runs what CI tested.
#
# No apt layer on purpose: the ctranslate2 wheels vendor their own libgomp and
# the av wheels bundle ffmpeg, on aarch64 as well as x86_64. Anything installed
# here would be paid for again on every emulated arm64 CI build.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /ws
COPY pyproject.toml uv.lock ./
COPY servers servers
RUN uv sync --frozen --no-dev --no-editable --package mcp-whisper

FROM python:3.12-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000

# Back both directories with volumes: WHISPER_MODEL_DIR holds the downloaded
# weights (a PVC keeps restarts from re-fetching them) and WHISPER_SPOOL_DIR
# holds uploaded audio awaiting transcription.
ENV WHISPER_MODEL_DIR=/models \
    WHISPER_SPOOL_DIR=/spool

CMD ["mcp-whisper"]
