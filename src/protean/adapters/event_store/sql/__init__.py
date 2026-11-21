"""The SQL event store, on SQLite and PostgreSQL through SQLAlchemy."""

from protean.infra.registry import event_stores


def register() -> None:
    """Register SqlEventStore with Protean as the `sql` event store."""
    # The class path keeps SQLAlchemy out of this import, so registering works
    # without the `sqlite` or `postgresql` extra. `get("sql")` then raises a
    # ConfigurationError that names both extras.
    event_stores.register("sql", "protean.adapters.event_store.sql.store.SqlEventStore")
