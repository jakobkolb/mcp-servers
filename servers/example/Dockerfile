FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

CMD ["uv", "run", "python", "-m", "example_server.server"]
