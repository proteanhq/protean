# Database-Specific Repositories

Protean supports binding repositories to specific database types, allowing you to write optimized queries for different databases while maintaining a single domain model.

## Overview

By default, a repository works with ALL databases (`database="ALL"`). When you need to optimize for a specific database — e.g., PostgreSQL-specific features like JSON operators, full-text search, or materialized views — you can create a database-specific repository.

Protean automatically selects the correct repository based on the active database provider.

## Code

The complete implementation is in [assets/repository_with_database.py](../assets/repository_with_database.py).

## How Database Selection Works

### Default Behavior: `database="ALL"`

```python
@domain.repository(part_of=Report)
class ReportRepository:
    """Works with any database."""
    def find_by_type(self, report_type):
        return self._dao.query.filter(report_type=report_type).all()
```

This repository is used regardless of which database provider is active.

### Database-Specific Binding

```python
@domain.repository(part_of=Report, database="postgresql")
class PostgresReportRepository:
    """Only used when the provider is PostgreSQL."""
    def find_by_type(self, report_type):
        # Can use PostgreSQL-specific query optimizations
        return self._dao.query.filter(report_type=report_type).all()
```

### Resolution Priority

When `domain.repository_for(Report)` is called:
1. Protean checks the active provider's database type (e.g., `"postgresql"`)
2. If a repository with `database="postgresql"` exists, it's used
3. Otherwise, the `database="ALL"` repository is used
4. If no custom repository exists at all, a default is generated

### Multiple Repositories Per Aggregate

You can have both a generic and a database-specific repository:

```python
@domain.repository(part_of=Report)  # database="ALL" (default)
class ReportRepository:
    """Generic repository — used for SQLite, in-memory, etc."""
    def find_by_type(self, report_type):
        return self._dao.query.filter(report_type=report_type).all()

@domain.repository(part_of=Report, database="postgresql")
class PostgresReportRepository:
    """PostgreSQL-specific — used when connected to PostgreSQL."""
    def find_by_type(self, report_type):
        return self._dao.query.filter(report_type=report_type).all()

    def find_high_value_reports(self, min_value):
        """PostgreSQL-optimized query."""
        return self._dao.query.filter(total_value__gte=min_value).all()
```

## Configuration

Database providers are configured in the domain's TOML configuration:

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://user:pass@localhost:5432/mydb"

[databases.analytics]
provider = "sqlite"
database_uri = "sqlite:///analytics.db"
```

The aggregate's `provider` option determines which database it connects to:

```python
@domain.aggregate(provider="analytics")
class AnalyticsReport:
    """Uses the 'analytics' SQLite database."""
    report_id: Identifier(identifier=True)
    # ...
```

## When to Use Database-Specific Repositories

Use database-specific repositories when:
- You need database-specific SQL features (JSON operators, window functions, etc.)
- Performance optimization requires database-native queries
- You're migrating between databases and need different implementations
- You have multiple databases serving different purposes (OLTP vs. OLAP)

## When NOT to Use

Stick with `database="ALL"` when:
- Standard query methods (filter, order_by, limit) are sufficient
- You want maximum portability across databases
- The application is in early development and the database isn't finalized

## Related
- [Default Repository](./default-repository.md) - Auto-generated generic repository
- [Custom Queries](./custom-queries.md) - Writing query methods
- [Anti-patterns](./anti-patterns.md) - Common mistakes
