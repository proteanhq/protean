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

# Mutation testing: find untested / under-asserted code paths by mutating a
# target module and checking whether its fast unit-test subset notices. Uses
# mutmut 3.x in a dedicated Python 3.12 env (.venv-mutation) — 3.14 is unreliable
# for this; the project .venv is left untouched. Override the module with
# TARGET=... (outbox | entity | status-field) and optionally focus the survivor
# report with MUT_FILTER="<grep on mutant names>" (e.g. a method name). See
# docs/community/contributing/mutation-testing.md.
TARGET ?= outbox
mutation:
	./scripts/mutation.sh $(TARGET)

cov: up
	uv run pytest --slow --sqlite --postgresql --elasticsearch --redis --message_db --cov=protean --cov-config .coveragerc tests
