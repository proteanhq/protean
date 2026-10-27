# Database-Specific Repositories

## Overview

By default, a repository works with all databases (`database="ALL"`). A repository bound to one database type, such as `database="postgresql"`, is selected when the active provider is that type. Use one for database-specific features such as JSON operators or full-text search.

## Code

The complete implementation is in [assets/repository_with_database.py](../assets/repository_with_database.py).

## How Database Selection Works

The examples on this page use this aggregate. The repositories filter on `report_type` and `total_value`, so it declares an index led by each:

```python
@domain.aggregate(indexes=[Index("report_type"), Index("total_value")])
class Report:
    report_id: Identifier(identifier=True)
    title: String(required=True, max_length=200)
    report_type: String(required=True, max_length=50)
    total_value: Decimal(precision=19, scale=4, default=0)
```

### Resolution Priority

When `domain.repository_for(Report)` is called:
1. Protean checks the active provider's database type (e.g., `"postgresql"`)
2. If a repository with `database="postgresql"` exists, it's used
3. Otherwise, the `database="ALL"` repository is used
4. If no custom repository exists at all, a default is generated

### Multiple Repositories Per Aggregate

One aggregate can have a generic and a database-specific repository:

```python
@domain.repository(part_of=Report)  # database="ALL" (default)
class ReportRepository:
    """Generic repository: used for SQLite, in-memory, etc."""
    def find_by_type(self, report_type):
        return self.query.filter(report_type=report_type).all()

@domain.repository(part_of=Report, database="postgresql")
class PostgresReportRepository:
    """PostgreSQL-specific: used when connected to PostgreSQL."""
    def find_by_type(self, report_type):
        return self.query.filter(report_type=report_type).all()

    def find_high_value_reports(self, min_value):
        """PostgreSQL-optimized query."""
        return self.query.filter(total_value__gte=min_value).all()
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

## Related
- [Default Repository](./default-repository.md): Auto-generated generic repository
- [Custom Queries](./custom-queries.md): Writing query methods
- [Anti-patterns](./anti-patterns.md): Common mistakes
