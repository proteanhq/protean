# PostgreSQL

The PostgreSQL adapter uses (`SQLAlchemy`)[https://www.sqlalchemy.org/] under
the covers as the ORM to communicate with the database.

## Prerequisites

To use the PostgreSQL adapter, you need to install additional dependencies:

1. **SQLAlchemy**: Required for all database operations (included when installing with `postgresql` extra)
2. **PostgreSQL Driver**: You need either `psycopg2` or `psycopg2-binary`

### Installing Dependencies

You can install Protean with PostgreSQL support using pip:

```bash
# Option 1: Use psycopg2-binary (easier installation, recommended for development)
pip install "protean[postgresql]"

# Option 2: Use psycopg2 (recommended for production)
pip install "protean[postgresql-dev]"
```

### psycopg2 vs psycopg2-binary

- `psycopg2-binary`: Pre-compiled binary package, easier to install but may have compatibility issues in some environments.
- `psycopg2`: Source distribution that requires compilation but generally more stable for production use.

### System Prerequisites for psycopg2

If you choose to use `psycopg2` (not the binary version), you'll need these system dependencies:

#### Ubuntu/Debian:
```bash
sudo apt-get install python3-dev libpq-dev
```

#### macOS with Homebrew:
```bash
brew install postgresql
```
After installation, you may need to set environment variables as instructed in the Homebrew output.

#### Windows:
Install PostgreSQL from the [official website](https://www.postgresql.org/download/windows/) which includes the required libraries.

## Configuration

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/postgres"
```

## Options

### provider

`postgresql` is the provider for PostgreSQL.

### database_uri

Connection string that specifies how to connect to a PostgreSQL database.

### schema

Specifies the database schema to use in the database.

## SQLAlchemy Model

You can supply a custom SQLAlchemy Model in place of the one that Protean
generates internally, allowing you full customization.

```python hl_lines="8-11 20-23"
{! docs_src/adapters/database/postgresql/001.py !}
```

!!!note
    The column names specified in the model should exactly match the attribute
    names of the Aggregate or Entity it represents.

