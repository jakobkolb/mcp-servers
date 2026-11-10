# Build context is the repository root:  docker build -f servers/example/Dockerfile .
# Dependencies come from the workspace's uv.lock (--frozen), so the image runs what CI tested.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /ws
COPY pyproject.toml uv.lock ./
COPY servers servers
RUN uv sync --frozen --no-dev --no-editable --package example-server

FROM python:3.12-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000
CMD ["example-server"]
