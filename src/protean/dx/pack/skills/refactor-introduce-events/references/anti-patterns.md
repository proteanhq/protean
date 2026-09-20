# Anti-Patterns When Introducing Events

## Circular event flows

```
Order ──OrderPlaced──> Inventory
Inventory ──StockReserved──> Order  # Creates infinite loop!
```

Fix: Use a process manager if you need bidirectional coordination, or reconsider
whether the second event is actually needed.

## Event handler modifying the source aggregate

```python
# Bad: event handler reaches back into the source
@domain.event_handler(part_of=Order, stream_category=Payment.meta_.stream_category)
class PaymentEventsHandler:
    @handle(PaymentProcessed)
    def on_payment(self, event):
        order = domain.repository_for(Order).get(event.order_id)
        order.mark_paid()
        domain.repository_for(Order).add(order)
        # This is OK! part_of=Order means this handler owns Order
```

This is actually correct — `part_of=Order` means the handler operates on Order.
The anti-pattern is when `part_of=Inventory` but the handler also modifies Order.

## Forgetting stream_category

```python
# Bad: won't receive Order events
@domain.event_handler(part_of=Inventory)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def reserve(self, event):
        ...  # Never called! No stream_category specified

# Good: subscribes to Order's stream
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def reserve(self, event):
        ...  # Called when OrderPlaced is raised
```

## Events as commands (imperative naming)

```python
# Bad: imperative name — this is a command, not an event
@domain.event(part_of="Order")
class ReserveInventory:
    product_id = String()
    quantity = Integer()

# Good: past tense — describes what happened
@domain.event(part_of="Order")
class OrderPlaced:
    product_id = String()
    quantity = Integer()
```

Events describe what happened. Commands describe what should happen.
The consumer decides what to do in response to the event.

## Synchronous expectations with async processing

```python
# Bad: expecting immediate consistency
@handle(PlaceOrder)
def place_order(self, command):
    order = Order(...)
    order.place()
    domain.repository_for(Order).add(order)
    # DON'T check inventory here — event hasn't been processed yet!
    inventory = domain.repository_for(Inventory).get(command.product_id)
    assert inventory.available < 100  # May not be true yet in async mode
```

In production (async mode), event handlers run later. Design for eventual consistency.

## Related

- [event-design-guide.md](event-design-guide.md) — How to design good events
