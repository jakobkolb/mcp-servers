SERVER        ?=
SERVERS       := $(wildcard servers/*)
DOCKERSERVERS := $(foreach d,$(SERVERS),$(if $(wildcard $(d)/Dockerfile),$(d)))
# Scaffold directories (no production code) excluded from static analysis
SCAFFOLD      := servers/example
MYPY_SRCS     := $(foreach d,$(filter-out $(SCAFFOLD),$(DOCKERSERVERS)),$(d)/src/)
CHART_DIR     := chart/mcp-server

.PHONY: install lint test build list-servers helm-lint helm-test helm clean test-watch

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

test-watch:
ifdef SERVER
	uv run ptw servers/$(SERVER) --now --patterns '*.py,pyproject.toml' --testmon -v --tb=short servers/$(SERVER)
else
	uv run ptw servers --now --patterns '*.py,pyproject.toml' --testmon -v --tb=short servers/
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

# Requires: helm, kubeconform
helm-lint:
	helm lint $(CHART_DIR)
	helm template test $(CHART_DIR) \
		--set image.repository=test \
		--set ingress.host=test.example.com \
		| kubeconform -strict -summary

# Requires: helm, helm-unittest plugin (helm plugin install https://github.com/helm-unittest/helm-unittest)
helm-test:
	helm unittest $(CHART_DIR)

helm: helm-lint helm-test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
