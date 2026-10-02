FROM python:3.12-slim

WORKDIR /app

# No apt layer on purpose: the ctranslate2 wheels vendor their own libgomp and
# the av wheels bundle ffmpeg, on aarch64 as well as x86_64. Anything installed
# here would be paid for again on every emulated arm64 CI build.
RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

# Back both directories with volumes: WHISPER_MODEL_DIR holds the downloaded
# weights (a PVC keeps restarts from re-fetching them) and WHISPER_SPOOL_DIR
# holds uploaded audio awaiting transcription.
ENV WHISPER_MODEL_DIR=/models \
    WHISPER_SPOOL_DIR=/spool

CMD ["uv", "run", "mcp-whisper"]
