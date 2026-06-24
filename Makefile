export COMPOSE_DOCKER_CLI_BUILD=1
export DOCKER_BUILDKIT=1

# All test/quality targets run through `uv run` so they always use the project
# .venv, never a stray interpreter on PATH (e.g. a pyenv shim with missing deps).

test:
	uv run protean test

build:
	docker-compose build

up:
	docker-compose up -d redis elasticsearch postgres message-db mssql

down:
	docker-compose down --remove-orphans

html:
	@cd docs-sphinx; $(MAKE) html

test-full: up
	uv run protean test -c FULL

test-flaky:
	uv run pytest -m flaky --no-header -rA --ignore=tests/support/

test-matrix:
	uv run nox -s tests

test-matrix-full: up
	uv run nox -s full

test-coverage: up
	uv run protean test -c COVERAGE

typecheck:
	uv run mypy src/protean --config-file pyproject.toml

cov: up
	uv run pytest --slow --sqlite --postgresql --elasticsearch --redis --message_db --cov=protean --cov-config .coveragerc tests
