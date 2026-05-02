FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY src/ src/
RUN uv sync --no-dev
# Mount your config at /config/calendars.yaml or set CALENDAR_CONFIG
ENV CALENDAR_CONFIG=/config/calendars.yaml
CMD ["uv", "run", "mcp-calendar"]
