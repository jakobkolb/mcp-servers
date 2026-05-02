FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

# Mount your config at /config/config.yaml or set CALENDAR_CONFIG
ENV CALENDAR_CONFIG=/config/config.yaml
CMD ["uv", "run", "mcp-calendar"]
