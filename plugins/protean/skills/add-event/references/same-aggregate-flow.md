# Same-Aggregate Event Flow

An event handler that belongs to and processes events from the same aggregate. Use this pattern when the side effect targets the aggregate that raised the event.

## Walkthrough

### The Event

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Decimal(precision=19, scale=4, required=True)
```

### The Aggregate Method

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Decimal(precision=19, scale=4, required=True)
    status: String(default="draft")
    confirmation_number: String()

    def place(self):
        if self.status != "draft":
            raise ValueError(f"Cannot place order in '{self.status}' status")
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total_amount=self.total_amount,
        ))
```

### The Event Handler

```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        repo.add(order)
```

With no `stream_category` specified, the handler defaults to Order's own stream.

## When to use same-aggregate handlers

Use this pattern for derived data (confirmation numbers, tracking codes), computed fields, and internal lifecycle transitions on the aggregate that raised the event.

**Not suitable when:**
- The side effect targets a different aggregate (use [cross-aggregate flow](./cross-aggregate-flow.md))
- You need to return a result to the caller (event handlers are fire-and-forget)

## Testing

When testing same-aggregate event flows:
1. Verify event is raised when aggregate method is called (check `aggregate._events`)
2. Verify handler processes the event correctly (check side effect on aggregate)
3. Test with synchronous processing (`domain.config["event_processing"] = "sync"`)

## Related
- [Cross-aggregate event flow](./cross-aggregate-flow.md): Event triggers side effect in another aggregate
- [Multiple events flow](./multiple-events-flow.md): Multiple events from one aggregate
- [event skill](../../event/SKILL.md): Detailed event definition reference
- [event-handler skill](../../event-handler/SKILL.md): Detailed handler reference
