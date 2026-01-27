# HDMI Matrix Proxy Makefile

# Configuration
IMAGE_NAME ?= ghcr.io/willysamz/hdmi-matrix-proxy
IMAGE_TAG ?= latest

# Python
PYTHON ?= python3
VENV ?= .venv

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# Development targets
.PHONY: install
install: ## Install dependencies in virtual environment
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt

.PHONY: dev
dev: ## Run development server with hot reload
	$(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

.PHONY: run
run: ## Run server without hot reload
	$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080

.PHONY: lint
lint: ## Run linting (ruff, mypy)
	$(VENV)/bin/ruff check app/
	$(VENV)/bin/ruff format --check app/
	$(VENV)/bin/mypy app/ --ignore-missing-imports

.PHONY: lint-fix
lint-fix: ## Fix linting issues automatically
	$(VENV)/bin/ruff check --fix app/
	$(VENV)/bin/ruff format app/

.PHONY: test
test: ## Run tests
	$(VENV)/bin/pytest tests/ -v

.PHONY: test-cov
test-cov: ## Run tests with coverage
	$(VENV)/bin/pytest tests/ -v --cov=app --cov-report=html

# Docker targets
.PHONY: build
build: ## Build Docker image
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

.PHONY: push
push: ## Push image to registry
	docker push $(IMAGE_NAME):$(IMAGE_TAG)

# Documentation targets
.PHONY: openapi
openapi: ## Generate OpenAPI spec
	PYTHONPATH=. $(VENV)/bin/python scripts/generate_openapi.py

# Version targets
.PHONY: version
version: ## Show current version
	@cat VERSION

.PHONY: bump-patch
bump-patch: ## Bump patch version (0.0.X)
	$(VENV)/bin/python scripts/bump_version.py patch

.PHONY: bump-minor
bump-minor: ## Bump minor version (0.X.0)
	$(VENV)/bin/python scripts/bump_version.py minor

.PHONY: bump-major
bump-major: ## Bump major version (X.0.0)
	$(VENV)/bin/python scripts/bump_version.py major

.PHONY: release
release: ## Create a release (bump patch, commit, tag, push)
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: Working directory not clean. Commit changes first."; \
		exit 1; \
	fi
	$(VENV)/bin/python scripts/bump_version.py patch
	@VERSION=$$(cat VERSION) && \
	git add -A && \
	git commit -m "chore: release v$$VERSION" && \
	git tag "v$$VERSION" && \
	echo "Created release v$$VERSION" && \
	echo "Run 'git push origin main --tags' to publish"

# Helm chart targets
.PHONY: helm-lint
helm-lint: ## Lint Helm chart
	helm lint ./chart

.PHONY: helm-template
helm-template: ## Render Helm templates locally
	helm template matrix ./chart

# Cleanup targets
.PHONY: clean
clean: ## Clean build artifacts
	rm -rf $(VENV)
	rm -rf __pycache__
	rm -rf app/__pycache__
	rm -rf app/routers/__pycache__
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
