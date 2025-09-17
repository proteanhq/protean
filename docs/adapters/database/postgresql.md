# PostgreSQL

The PostgreSQL adapter uses (`SQLAlchemy`)[https://www.sqlalchemy.org/] under
the covers as the ORM to communicate with the database.

## Installing

To use the PostgreSQL adapter, simply install Protean with the PostgreSQL extra:


```bash
# Use psycopg2
pip install "protean[postgresql-dev]"
```



### System Prerequisites for psycopg2

If you choose to use `psycopg2` (not the binary version), you'll need to install some system dependencies. Please refer to the [official psycopg2 installation guide](https://www.psycopg.org/docs/install.html#quick-install) for up-to-date installation instructions for your operating system.


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

## Troubleshooting

### Missing Dependencies

If you encounter errors about missing dependencies, you'll see helpful warning messages that guide you to install the necessary packages. Common errors include:

- `ImportError: No module named 'psycopg2'`: Install either `psycopg2` or `psycopg2-binary`
- Compilation errors with `psycopg2`: Install the system dependencies mentioned above

### Connection Issues

- Ensure PostgreSQL is running on the specified host and port
- Verify the database user has appropriate permissions
- Check if the database specified in the URI exists

