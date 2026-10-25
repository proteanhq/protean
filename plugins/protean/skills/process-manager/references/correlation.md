# Correlation

Correlation determines which process manager instance handles each incoming event. Every handler in a process manager must declare a `correlate` parameter that extracts an identity value from the event.

## Overview

When an event arrives, the framework:

1. Reads the `correlate` spec from the matched handler
2. Extracts the correlation value from the event
3. Builds the stream name: `{pm_stream_category}-{correlation_value}`
4. Loads the PM instance by replaying transition events from that stream
5. If no instance exists and `start=True`, creates a new one
6. If no instance exists and `start=False`, silently skips the event

## String Correlation

The simplest form names the event field that holds the correlation value. With `correlate="order_id"`, the framework reads `event.order_id` and uses its value to find or create the PM instance.

## Dictionary Correlation

When the event carries the value under a different name than the PM field, use a dictionary mapping. The format is `{pm_field_name: event_field_name}`. The SKILL.md's `PaymentReconciliationPM` uses `correlate={"order_id": "ext_order_ref"}`: the framework reads `event.ext_order_ref` to route the event, and the handler stores that value in `order_id`.

## Correlation Consistency

All events in a process must be routable to the same PM instance. The framework matches by value. It reads the correlation value from each event and looks up the PM instance by that value alone. Field names play no part in the lookup.

- **String correlation**: `correlate="order_id"` reads `event.order_id`. Handlers can name different fields, such as `order_id` on one event and `payment_order_id` on another, as long as both fields hold the same value.
- **Dictionary correlation**: `correlate={"order_id": "ext_order_ref"}` reads `event.ext_order_ref`. The framework uses only the dict's value. The key documents which PM field the value belongs to.

```python
# fragment
# Events from different aggregates with consistent correlation
@handle(OrderPlaced, start=True, correlate="order_id")        # event.order_id
@handle(PaymentConfirmed, correlate="order_id")                # event.order_id
@handle(ShipmentDelivered, correlate="order_id")               # event.order_id

# OR with dict correlation when names differ
@handle(ExternalPaymentReceived, correlate={"order_id": "ext_ref"})  # event.ext_ref → order_id
@handle(InternalReconciled, correlate={"order_id": "order_reference"})  # event.order_reference → order_id
```

What breaks routing: an attribute whose value does not match the target instance's identifying value, or an attribute the event does not carry at all (raises `AttributeError`).

## Stream Naming

The PM's stream name is derived from the correlation value:

```
{pm_stream_category}-{correlation_value}
```

For example, if the PM's stream category is `ecommerce::order_fulfillment_pm` and the correlation value is `ORD-123`, the stream name is:

```
ecommerce::order_fulfillment_pm-ORD-123
```

All transition events for this PM instance are stored in this stream.

## Related

- [Lifecycle Management](./lifecycle.md): How correlation interacts with start/end
- [Event Handler skill](../../event-handler/SKILL.md): Compare with stateless handlers (no correlation)
