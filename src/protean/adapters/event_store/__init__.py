from protean.infra.registry import event_stores as event_store_registry


def register_message_db() -> None:
    """Register MessageDBStore with Protean as the `message_db` event store."""
    # Lives here, away from message_db.py, so that registering the name does not
    # import psycopg2. Without the extra installed, `get("message_db")` then
    # fails naming the missing module instead of reporting an unknown name.
    event_store_registry.register(
        "message_db", "protean.adapters.event_store.message_db.MessageDBStore"
    )
