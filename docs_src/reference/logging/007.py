# --8<-- [start:log-snapshot-event]
from protean.integrations.logging import (
    SNAPSHOT_EVENT_DISCARDED,
    log_snapshot_event,
)

log_snapshot_event(
    SNAPSHOT_EVENT_DISCARDED,
    aggregate="User",
    aggregate_id="user-1",
    reason="extra fields not permitted",
)
# --8<-- [end:log-snapshot-event]
