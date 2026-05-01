SERVER ?=
SERVERS := $(wildcard servers/*)

.PHONY: install lint test build clean

install:
	uv sync --all-packages

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy servers/

test:
ifdef SERVER
	uv run pytest servers/$(SERVER) -v --tb=short
else
	uv run pytest servers/ -v --tb=short
endif

build:
ifdef SERVER
	docker build -t mcp-$(SERVER):latest servers/$(SERVER)
else
	@for server in $(SERVERS); do \
		name=$$(basename $$server); \
		echo "Building mcp-$$name..."; \
		docker build -t mcp-$$name:latest $$server; \
	done
endif

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
