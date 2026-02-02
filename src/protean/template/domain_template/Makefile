.PHONY: help install test test-unit test-integration test-bdd test-cov lint format typecheck clean run shell server migrate

# Default target
help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# Installation and Setup
install: ## Install dependencies using Poetry
	poetry install --with dev,test,docs,types

install-pre-commit: ## Install pre-commit hooks
	poetry run pre-commit install

# Testing
test: ## Run all tests
	poetry run pytest

test-domain: ## Run domain layer tests (100% coverage required)
	poetry run pytest tests/{{ package_name }}/domain/ --cov=src/{{ package_name }} --cov-fail-under=100 --cov-report=term-missing

test-application: ## Run application layer tests (100% coverage required)
	poetry run pytest tests/{{ package_name }}/application/ --cov=src/{{ package_name }} --cov-fail-under=100 --cov-report=term-missing

test-integration: ## Run integration tests (90% coverage required)
	poetry run pytest tests/{{ package_name }}/integration/ --cov=src/{{ package_name }} --cov-fail-under=90 --cov-report=term-missing

test-fast: ## Run fast tests (domain + application)
	poetry run pytest tests/{{ package_name }}/domain/ tests/{{ package_name }}/application/ -m "not slow"

test-cov: ## Run all tests with full coverage report
	poetry run pytest --cov=src/{{ package_name }} --cov-report=term-missing --cov-report=html --cov-report=xml

test-cov-domain: ## Run domain tests with coverage report
	poetry run pytest tests/{{ package_name }}/domain/ --cov=src/{{ package_name }} --cov-report=term-missing --cov-report=html:htmlcov/domain

test-cov-application: ## Run application tests with coverage report
	poetry run pytest tests/{{ package_name }}/application/ --cov=src/{{ package_name }} --cov-report=term-missing --cov-report=html:htmlcov/application

test-cov-integration: ## Run integration tests with coverage report
	poetry run pytest tests/{{ package_name }}/integration/ --cov=src/{{ package_name }} --cov-report=term-missing --cov-report=html:htmlcov/integration

test-watch: ## Run tests in watch mode
	poetry run pytest-watch

# Code Quality
lint: ## Run linting with ruff
	poetry run ruff check src/ tests/

format: ## Format code with ruff
	poetry run ruff format src/ tests/

typecheck: ## Run type checking with mypy
	poetry run mypy src/

check: lint typecheck test ## Run all checks (lint, typecheck, test)

pre-commit: ## Run pre-commit hooks on all files
	poetry run pre-commit run --all-files

# Protean Commands
shell: ## Start Protean shell
	poetry run protean shell

server: ## Start Protean server for async message processing
	poetry run protean server

generate-docker: ## Generate docker-compose file for infrastructure
	poetry run protean generate docker

# Docker
docker-up: ## Start Docker services
	docker-compose up -d

docker-down: ## Stop Docker services
	docker-compose down

docker-logs: ## View Docker logs
	docker-compose logs -f

docker-clean: ## Clean Docker volumes
	docker-compose down -v

docker-build: ## Build application Docker image
	docker build -t {{ package_name }}:latest .

docker-build-dev: ## Build development Docker image
	docker build -f Dockerfile.dev -t {{ package_name }}:dev .

docker-run: ## Run application in Docker
	docker-compose up app

docker-run-detached: ## Run application in Docker (detached)
	docker-compose up -d app

docker-shell: ## Open shell in application container
	docker-compose run --rm app /bin/bash

docker-exec: ## Execute command in running container
	docker-compose exec app $(cmd)

docker-ps: ## List running containers
	docker-compose ps

docker-restart: ## Restart all services
	docker-compose restart

docker-rebuild: ## Rebuild and restart all services
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d

docker-prod: ## Run production stack
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

docker-prod-logs: ## View production logs
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

docker-prod-down: ## Stop production stack
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

# Development
dev: docker-up ## Start development environment (Docker services only)

# Database
migrate: ## Run database migrations
	@echo "Add your migration command here"

# Cleanup
clean: ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true

# Documentation
docs: ## Build documentation
	poetry run mkdocs build

docs-serve: ## Serve documentation locally
	poetry run mkdocs serve