# Event Handlers

Event handlers consume events raised in an aggregate and help sync the state of
the aggregate with other aggregates and other systems. They are the preferred
mechanism to update multiple aggregates.

## Defining an Event Handler

Event Handlers are defined with the `Domain.event_handler` decorator. Below is
a simplified example of an Event Handler connected to `Inventory` aggregate
syncing stock levels corresponding to changes in the `Order` aggregate.

```python hl_lines="26-27 44"
{! docs_src/guides/propagate-state/001.py !}
```

1. `Order` aggregate fires `OrderShipped` event on book being shipped.

2. Event handler picks up the event and updates stock levels in `Inventory`
aggregate.

Simulating a hypothetical example, we can see that the stock levels were
decreased in response to the `OrderShipped` event.

```shell hl_lines="21"
In [1]: order = Order(book_id=1, quantity=10, total_amount=100)

In [2]: domain.repository_for(Order).add(order)
Out[2]: <Order: Order object (id: 62f8fa8d-2963-4539-bd21-860d3bab639e)>

In [3]: inventory = Inventory(book_id=1, in_stock=100)

In [4]: domain.repository_for(Inventory).add(inventory)
Out[4]: <Inventory: Inventory object (id: 9272d70f-b796-417d-8f30-e01302d9f1a9)>

In [5]: order.ship_order()

In [6]: domain.repository_for(Order).add(order)
Out[6]: <Order: Order object (id: 62f8fa8d-2963-4539-bd21-860d3bab639e)>

In [7]: stock = domain.repository_for(Inventory).get(inventory.id)

In [8]: stock.to_dict()
Out[8]: {
 'book_id': '1',
 'in_stock': 90,
 'id': '9272d70f-b796-417d-8f30-e01302d9f1a9'
 }
```

## Configuration Options

- **`part_of`**: The aggregate to which the event handler is connected.
- **`stream_name`**: The event handler listens to events on this stream.
The stream name defaults to the aggregate's stream. This option comes handy
when the event handler belongs to an aggregate and needs to listen to another
aggregate's events.
- **`source_stream`**: When specified, the event handler only consumes events
generated in response to events or commands from this original stream.
For example, `EmailNotifications` event handler listening to `OrderShipped`
events can be configured to generate a `NotificationSent` event only when the
`OrderShipped` event (in stream `orders`) is generated in response to a
`ShipOrder` (in stream `manage_order`) command.
