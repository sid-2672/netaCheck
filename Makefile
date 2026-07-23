.PHONY: help dev stop test lint format typecheck migrate migrate-down \
        migrate-create seed shell clean build logs

# Default Python executable (use the venv if it exists)
PYTHON := $(shell which python3.12 2>/dev/null || which python3 2>/dev/null || echo python3)
BACKEND_DIR := backend

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help: ## Show this help message
	@echo "NetaCheck — Development Commands"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "%-22s %s\n", "Command", "Description"} \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' \
	      $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install: ## Install backend dependencies in a virtual environment
	cd $(BACKEND_DIR) && \
	    $(PYTHON) -m venv .venv && \
	    .venv/bin/pip install --upgrade pip && \
	    .venv/bin/pip install -e ".[dev]"

install-hooks: ## Install pre-commit hooks
	cd $(BACKEND_DIR) && .venv/bin/pre-commit install

setup: install install-hooks ## Full developer setup (install deps + hooks)
	cp -n .env.example .env || true
	@echo ""
	@echo "✅  Setup complete. Edit .env with your values then run: make dev"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev: ## Start all services (Postgres + Redis + Backend)
	docker compose up --build

dev-db: ## Start only the database services (Postgres + Redis)
	docker compose up postgres redis

dev-backend: ## Start the backend directly (requires DB running)
	cd $(BACKEND_DIR) && \
	    RELOAD=true .venv/bin/uvicorn netacheck.main:app \
	    --host 0.0.0.0 --port 8000 --reload --log-config /dev/null

stop: ## Stop all running containers
	docker compose down

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: ## Run all backend tests
	cd $(BACKEND_DIR) && .venv/bin/pytest

test-unit: ## Run only unit tests
	cd $(BACKEND_DIR) && .venv/bin/pytest tests/unit/ -v

test-integration: ## Run only integration tests
	cd $(BACKEND_DIR) && .venv/bin/pytest tests/integration/ -v

test-watch: ## Run tests in watch mode (requires pytest-watch)
	cd $(BACKEND_DIR) && .venv/bin/ptw -- -v

test-cov: ## Run tests and open HTML coverage report
	cd $(BACKEND_DIR) && \
	    .venv/bin/pytest && \
	    open htmlcov/index.html

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
lint: ## Run Ruff linter
	cd $(BACKEND_DIR) && .venv/bin/ruff check src/ tests/

lint-fix: ## Run Ruff linter with auto-fix
	cd $(BACKEND_DIR) && .venv/bin/ruff check --fix src/ tests/

format: ## Format code with Black
	cd $(BACKEND_DIR) && .venv/bin/black src/ tests/

format-check: ## Check formatting without writing changes
	cd $(BACKEND_DIR) && .venv/bin/black --check src/ tests/

typecheck: ## Run Mypy type checker
	cd $(BACKEND_DIR) && .venv/bin/mypy src/netacheck/

check: lint format-check typecheck ## Run all checks (lint + format + types)

# ---------------------------------------------------------------------------
# Database / Alembic
# ---------------------------------------------------------------------------
migrate: ## Apply all pending migrations
	cd $(BACKEND_DIR) && .venv/bin/alembic upgrade head

migrate-down: ## Rollback the last migration
	cd $(BACKEND_DIR) && .venv/bin/alembic downgrade -1

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add foo")
	@test -n "$(MSG)" || (echo "Error: MSG is required. Usage: make migrate-create MSG='add foo'" && exit 1)
	cd $(BACKEND_DIR) && .venv/bin/alembic revision --autogenerate -m "$(MSG)"

migrate-history: ## Show migration history
	cd $(BACKEND_DIR) && .venv/bin/alembic history --verbose

migrate-current: ## Show current migration version
	cd $(BACKEND_DIR) && .venv/bin/alembic current

seed: ## Load development seed data
	cd $(BACKEND_DIR) && .venv/bin/python -m netacheck.scripts.seed

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
shell: ## Open a Python shell with the app context loaded
	cd $(BACKEND_DIR) && .venv/bin/python -c \
	    "import asyncio; from netacheck.core.database import async_session_factory; \
	     print('Session factory ready. Use: asyncio.run(your_coroutine())')"

logs: ## Follow Docker logs for all services
	docker compose logs -f

logs-backend: ## Follow Docker logs for the backend only
	docker compose logs -f backend

clean: ## Remove Python caches, coverage reports, and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅  Cleaned."

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
build: ## Build Docker images
	docker compose build

push: ## Push Docker images to registry (requires REGISTRY env var)
	docker compose push

# ---------------------------------------------------------------------------
# Ingestion (Phase 3+)
# ---------------------------------------------------------------------------
ingest-adr: ## Run ADR scraper for the pilot batch
	cd $(BACKEND_DIR) && .venv/bin/python -m netacheck.scripts.ingest --source adr

ingest-prs: ## Run PRS scraper
	cd $(BACKEND_DIR) && .venv/bin/python -m netacheck.scripts.ingest --source prs
