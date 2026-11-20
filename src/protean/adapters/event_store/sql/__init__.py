"""The SQL event store, on SQLite and PostgreSQL through SQLAlchemy."""

from protean.infra.registry import event_stores


def register() -> None:
    """Register SqlEventStore with Protean as the `sql` event store."""
    # The class path keeps SQLAlchemy out of this import. Without the `sqlite`
    # or `postgresql` extra, `get("sql")` then fails naming the extras instead
    # of reporting an unknown name.
    event_stores.register("sql", "protean.adapters.event_store.sql.store.SqlEventStore")
