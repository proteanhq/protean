# Anti-Patterns When Introducing Events

## Circular event flows

```
Order ──OrderPlaced──> Inventory
Inventory ──StockReserved──> Order  # Creates infinite loop!
```

Fix: Use a process manager if you need bidirectional coordination, or reconsider
whether the second event is actually needed.

## Event handler in the target aggregate's cluster

```python
# fragment
# Bad: Inventory's cluster handles Order's event. `check` reports this as
# EVENT_HANDLER_FOREIGN_EVENT.
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def reserve(self, event):
        inventory = current_domain.repository_for(Inventory).get(event.product_id)
        inventory.reserve(event.order_id, event.quantity)
        current_domain.repository_for(Inventory).add(inventory)
```

The handler reacts to an event that another cluster owns. Put the handler in the
cluster that owns the event, and hand off to the target aggregate with a command:

```python
# fragment
# Good: the handler sits in Order's cluster and issues a command to Inventory
@domain.event_handler(part_of=Order)
class InventoryReservation:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )
```

`ReserveStock` is `part_of=Inventory`, and `Inventory`'s command handler does the
write. Events are delivered at least once, so that command handler returns without
changes when the order id is already in `Inventory.reserved_order_ids`. For a flow
with several causally dependent steps, use a
[process manager](../../process-manager/SKILL.md).

## Events as commands (imperative naming)

```python
# fragment
# Bad: imperative name — this is a command, not an event
@domain.event(part_of="Order")
class ReserveInventory:
    product_id = String()
    quantity = Integer()
```

```python
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
# fragment
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
