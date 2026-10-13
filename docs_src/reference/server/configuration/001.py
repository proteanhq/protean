# ruff: noqa: B018
# Bare dict literals, as the page shows them. The test reads each one back
# from its section text and compares it with the resolved configuration.

# --8<-- [start:production]
{
    "subscription_type": "stream",
    "messages_per_tick": 100,
    "tick_interval": 0,
    "blocking_timeout_ms": 5000,
    "max_retries": 3,
    "retry_delay_seconds": 1,
    "enable_dlq": True,
    "position_update_interval": 10,
    "circuit_breaker_threshold": 10,
    "circuit_breaker_reset_seconds": 60,
    "retention_maxlen": 100_000,
}
# --8<-- [end:production]

# --8<-- [start:fast]
{
    "subscription_type": "stream",
    "messages_per_tick": 10,
    "tick_interval": 0,
    "blocking_timeout_ms": 100,
    "max_retries": 2,
    "retry_delay_seconds": 0,
    "enable_dlq": True,
    "position_update_interval": 5,
    "circuit_breaker_threshold": 10,
    "circuit_breaker_reset_seconds": 60,
    "retention_maxlen": 100_000,
}
# --8<-- [end:fast]

# --8<-- [start:batch]
{
    "subscription_type": "stream",
    "messages_per_tick": 500,
    "tick_interval": 0,
    "blocking_timeout_ms": 10000,
    "max_retries": 5,
    "retry_delay_seconds": 2,
    "enable_dlq": True,
    "position_update_interval": 50,
    "circuit_breaker_threshold": 10,
    "circuit_breaker_reset_seconds": 60,
    "retention_maxlen": 500_000,
}
# --8<-- [end:batch]

# --8<-- [start:debug]
{
    "subscription_type": "stream",
    "messages_per_tick": 1,
    "tick_interval": 1,
    "blocking_timeout_ms": 1000,
    "max_retries": 1,
    "retry_delay_seconds": 0,
    "enable_dlq": False,
    "position_update_interval": 1,
    "circuit_breaker_threshold": 10,
    "circuit_breaker_reset_seconds": 60,
    "retention_maxlen": 1_000,
}
# --8<-- [end:debug]

# --8<-- [start:projection]
{
    "subscription_type": "event_store",
    "messages_per_tick": 100,
    "tick_interval": 0,
    "position_update_interval": 10,
    "enable_dlq": False,  # Not supported for event_store
    "retention_maxlen": None,  # Reads the event store, not a broker stream
}
# --8<-- [end:projection]
