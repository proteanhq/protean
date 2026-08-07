
# `protean new`

The `protean new` command initializes a new project with a given name.

## Usage

```shell
protean new [OPTIONS] PROJECT_NAME
```

## Arguments

| Argument       | Description             | Default | Required |
|----------------|-------------------------|---------|----------|
| `PROJECT_NAME` | Name of the new project | None    | Yes      |

## Options

- `--output-dir`, `-o`: Specifies the directory where the project should be
created. If not provided, the current directory is used.

!!! note
    Throws an error if the output directory is not found or not empty.
    Combine with `--force` to overwrite existing directory.

- `--data`, `-d`: Accepts one or more key-value pairs to be included in
the project's configuration. Available configuration options include:
    - `author_name`: Project author name
    - `author_email`: Project author email
    - `short_description`: Brief project description
    - `database`: Database choice (`memory`, `postgresql`, `sqlite`, `elasticsearch`)
    - `broker`: Message broker choice (`inline`, `redis`, `redis-pubsub`)
    - `include_example`: Include example domain code (`true`/`false`)

- `--defaults`: Use default values for all prompts without interaction
- `--skip-setup`: Skip running setup commands (useful for testing)
- `--help`: Shows the help message and exits.

### Behavior Modifiers

- `--pretend`, `-p`: Runs the command in a "dry run" mode, showing what
would be done without making any changes.
- `--force`, `-f`: Forces the command to run even if it would overwrite
existing files.

## Generated Project Structure

The command creates a complete project structure with the following components:

### Root Files

- `pyproject.toml` - Python project configuration with uv
- `README.md` - Project documentation
- `Makefile` - Common development tasks
- `.gitignore` - Git ignore patterns
- `.pre-commit-config.yaml` - Pre-commit hooks configuration
- `.env.example` - Environment variables template
- `logging.toml` - Logging configuration
- `.dockerignore` - Docker ignore patterns

### Docker Configuration

- `Dockerfile` - Production Docker image
- `Dockerfile.dev` - Development Docker image
- `docker-compose.yml` - Base docker-compose configuration
- `docker-compose.override.yml` - Local development overrides
- `docker-compose.prod.yml` - Production configuration
- `nginx.conf` - Nginx configuration for production

### Activation Scripts

The `scripts/` directory contains virtual environment activation scripts for different shells:

- `scripts/activate.sh` - Bash/Zsh activation
- `scripts/activate.fish` - Fish shell activation
- `scripts/activate.bat` - Windows batch activation

### Source Code Structure

The generated structure follows the
[Organize by Domain Concept](../../../patterns/organize-by-domain-concept.md)
pattern. The folder tree is organized around **what the system does**
(domain concepts), not around technical layers. Protean's decorators carry
architectural metadata (which layer, which side), so the folder structure
doesn't need to repeat it.

```
src/
└── <package_name>/
    ├── __init__.py
    ├── domain.py          # Domain initialization
    ├── domain.toml        # Domain configuration
    ├── shared/            # Shared domain vocabulary and utilities
    │   ├── __init__.py
    │   ├── logging.py     # Structured logging setup
    │   ├── exceptions.py  # Domain exceptions
    │   └── value_objects.py
    └── example/           # Optional example aggregate
        ├── __init__.py
        ├── aggregate.py       # Example aggregate with a create() factory
        ├── commands.py        # CreateExample
        ├── command_handlers.py
        ├── events.py          # ExampleCreated
        ├── projection.py      # ExampleSummary read model
        └── projectors.py      # Builds ExampleSummary from ExampleCreated
```

The example is a minimal walking skeleton: one command creates the aggregate,
which raises one event, which a projector turns into one read model. It shows
the write path and the read path end to end with nothing to trim before you
start. Delete the `example/` folder (or pass `--data include_example=false`)
once you have your own aggregates.

Key structural decisions:

- **Aggregates are top-level folders** — each aggregate (`example/`) is a
  chapter heading a business stakeholder would recognize.
- **Projections live with the aggregate that sources them** — `projection.py`
  (the read model) and `projectors.py` (the code that keeps it current) sit
  inside `example/`. As projections grow to span aggregates, lift them into a
  domain-level `projections/` folder.
- **Shared vocabulary has its own folder** — cross-aggregate value objects
  and utilities live in `shared/`.
- **`domain.py` and `domain.toml` are front matter** — a newcomer sees
  what this bounded context is and how it's configured immediately.

As your domain grows, add new aggregates as peer folders alongside
`example/`. See the
[Organize by Domain Concept](../../../patterns/organize-by-domain-concept.md)
pattern for guidance on evolving this structure, including colocating
commands with their handlers in capability files.

### Test Structure

```
tests/
├── README.md
└── <package_name>/
    ├── conftest.py         # Initialises the domain for the test session
    ├── domain/            # Domain logic tests
    │   └── __init__.py
    ├── application/       # Application layer tests
    │   ├── __init__.py
    │   └── test_example.py   # Write- and read-path tests for the example
    └── integration/       # Integration tests
        └── __init__.py
```

The example ships with two passing tests (only when `include_example` is
true): one drives the command/event write path, the other asserts the
projection reflects the created aggregate. `pytest` runs green on a fresh
project, so you have a working test to copy from on day one.

### CI/CD Configuration

- `.github/workflows/ci.yml` - GitHub Actions CI pipeline

## Generated Modules

### Logging Module (`shared/logging.py`)

The generated logging module provides structured logging with:

- **JSON formatting** for production environments
- **Readable formatting** for development
- **Log rotation support** with size-based rotation
- **Environment-specific log levels** (DEBUG, INFO, WARNING, ERROR)

**Key Features:**

- `get_logger(name)` - Get a configured structlog logger
- `add_context(**kwargs)` - Add context variables to all subsequent logs
- `clear_context()` - Clear all context variables
- `log_method_call` - Decorator for logging method calls
- `configure_for_testing()` - Reduce verbosity during tests

**Environment Configuration:**

The logging level is determined by the `ENVIRONMENT` variable:
- `production`/`staging`: INFO level
- `development`: DEBUG level
- `test`: WARNING level

Override with the `LOG_LEVEL` environment variable.

### Exceptions Module (`shared/exceptions.py`)

Domain-specific exception hierarchy:

- `DomainException` - Base exception for all domain errors
- `InvalidStateException` - Operation attempted in invalid state
- `NotFoundException` - Requested resource not found
- `DuplicateException` - Duplicate resource creation attempt
- `ValidationException` - Domain validation failure

## Examples

### Creating a New Project

To create a new project named "authentication" in the current directory:

```shell
protean new authentication
```

### Specifying an Output Directory

To create a new project in a specific directory:

```shell
protean new authentication -o /path/to/directory
```

### Using Configuration Data

To create a project with PostgreSQL and Redis:

```shell
protean new authentication \
  -d author_name="John Doe" \
  -d author_email=john@example.com \
  -d database=postgresql \
  -d broker=redis
```

### Creating a Project with Example Code

To include example domain code (aggregate, commands, events, handlers):

```shell
protean new authentication \
  -d include_example=true \
  --defaults
```

### Quick Setup with Defaults

To quickly create a project with default options:

```shell
protean new my_project --defaults
```
