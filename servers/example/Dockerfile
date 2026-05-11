FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "example-server"]
