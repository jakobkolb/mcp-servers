FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

# Pass OBSIDIAN_API_KEY, OBSIDIAN_HOST, OBSIDIAN_PORT at runtime via -e flags
CMD ["uv", "run", "mcp-obsidian"]
