SERVER        ?=
SERVERS       := $(wildcard servers/*)
DOCKERSERVERS := $(foreach d,$(SERVERS),$(if $(wildcard $(d)/Dockerfile),$(d)))
# Scaffold directories (no production code) excluded from static analysis
SCAFFOLD      := servers/example
MYPY_SRCS     := $(foreach d,$(filter-out $(SCAFFOLD),$(DOCKERSERVERS)),$(d)/src/)

.PHONY: install lint test build list-servers clean

install:
	uv sync --all-packages

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy $(MYPY_SRCS)

test:
ifdef SERVER
	uv run pytest servers/$(SERVER) -v --tb=short
else
	uv run pytest servers/ -v --tb=short
endif

# Outputs a JSON array of server names that have a Dockerfile (consumed by CI).
list-servers:
	@for d in $(DOCKERSERVERS); do basename "$$d"; done | jq -R . | jq -sc .

build:
ifdef SERVER
	docker build -t mcp-$(SERVER):latest servers/$(SERVER)
else
	@for server in $(DOCKERSERVERS); do \
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
