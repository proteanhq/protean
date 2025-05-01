# PostgreSQL

## 🛠️ PostgreSQL Setup Guide

### 1. Install PostgreSQL

Ubuntu/Debian:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib```

The PostgreSQL adapter uses [SQLAlchemy](https://www.sqlalchemy.org/) under the hood as the ORM to communicate with the database.
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

