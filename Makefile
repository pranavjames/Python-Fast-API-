.DEFAULT_GOAL := help
PY ?= python

.PHONY: help install lint format typecheck test cov migrate revision run admin docker-up docker-down

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies and git hooks
	$(PY) -m pip install -r requirements-dev.txt
	pre-commit install

lint: ## Run ruff lint and format checks
	ruff check .
	ruff format --check .

format: ## Auto-format and fix lint issues
	ruff format .
	ruff check --fix .

typecheck: ## Run mypy in strict mode
	mypy app

test: ## Run the test suite
	pytest

cov: ## Run tests with coverage report
	pytest --cov --cov-report=term-missing

migrate: ## Apply database migrations
	alembic upgrade head

revision: ## Create a migration: make revision m="add column"
	alembic revision --autogenerate -m "$(m)"

run: ## Start the dev server with auto-reload
	uvicorn app.main:app --reload --port 8000

admin: ## Create an admin: make admin email=you@example.com
	$(PY) -m app.commands.create_admin --email "$(email)"

docker-up: ## Build and start the API + MySQL stack
	docker compose up --build -d

docker-down: ## Stop the stack
	docker compose down
