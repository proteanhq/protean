# --8<-- [start:log-security-event]
from protean.integrations.logging import (
    SECURITY_EVENT_INVARIANT_FAILED,
    log_security_event,
)

log_security_event(
    SECURITY_EVENT_INVARIANT_FAILED,
    aggregate="Order",
    aggregate_id="ord-9b1c",
    invariant="total_must_equal_sum_of_items",
)
# --8<-- [end:log-security-event]

# --8<-- [start:security-constants]
from protean.integrations.logging import (
    SECURITY_EVENT_INVALID_OPERATION,  # "invalid_operation"
    SECURITY_EVENT_INVALID_STATE,  # "invalid_state"
    SECURITY_EVENT_INVARIANT_FAILED,  # "invariant_failed"
    SECURITY_EVENT_VALIDATION_FAILED,  # "validation_failed"
)

# --8<-- [end:security-constants]

event_types = (
    SECURITY_EVENT_INVARIANT_FAILED,
    SECURITY_EVENT_VALIDATION_FAILED,
    SECURITY_EVENT_INVALID_OPERATION,
    SECURITY_EVENT_INVALID_STATE,
)
