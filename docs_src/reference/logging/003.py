# --8<-- [start:get-logger]
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info("order_placed", order_id="ord-123", total=99.95)
# --8<-- [end:get-logger]

# The page shows bind-event-context first. It runs last here so the
# add-context section's clear_context() does not wipe its binding.

# --8<-- [start:add-context]
from protean.utils.logging import add_context, clear_context

add_context(request_id="req-abc", tenant_id="tenant-42")
logger.info("checkout_started")  # carries request_id and tenant_id
clear_context()
# --8<-- [end:add-context]

# --8<-- [start:bind-event-context]
from protean.utils.logging import bind_event_context, unbind_event_context

bind_event_context(user_id="u-42", plan="premium")
unbind_event_context("plan")
# --8<-- [end:bind-event-context]
