# Anti-Patterns Catalog

Comprehensive catalog of anti-patterns found in Protean codebases, organized by how commonly they appear.

## Tier 1: Almost Universal

These appear in nearly every codebase that hasn't been through a design review.

### The "Controller Handler"

Handler does everything — validates, calculates, constructs, persists, and coordinates:

```python
# fragment
# Bad: handler is a controller
@handle(PlaceOrder)
def place_order(self, command):
    if not command.items:
        raise ValidationError("Empty order")
    total = sum(i.price * i.qty for i in command.items)
    if total > MAX_ORDER:
        raise ValidationError("Too expensive")
    order = Order(customer_id=command.customer_id, total=total, status="PLACED")
    current_domain.repository_for(Order).add(order)
```

```python
@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = Identifier(required=True)
    items = List(content_type=Dict())


# Good: handler orchestrates, aggregate owns logic
@domain.command_handler(part_of="Order")
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        order = Order(customer_id=command.customer_id)
        order.place(items=command.items)
        current_domain.repository_for(Order).add(order)
        return order.id
```

### Primitive Obsession

Using raw fields where value objects should model domain concepts:

```python
# fragment
# Bad: raw fields
class Order:
    total_amount = Float()
    total_currency = String(default="USD")
    shipping_street = String()
    shipping_city = String()
    shipping_zip = String()
```

```python
@domain.value_object
class Money:
    amount = Decimal(required=True, precision=19, scale=4)
    currency = String(max_length=3, default="USD")


@domain.value_object
class Address:
    street = String(required=True)
    city = String(required=True)
    zip_code = String(required=True)


# Good: value objects
@domain.aggregate
class Order:
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)
```

### The "Anemic Aggregate"

Aggregate is just a data container with no behavior:

```python
# fragment
# Bad: anemic — no methods, no invariants
@domain.aggregate
class Order:
    customer_id = String(required=True)
    status = String(default="DRAFT")
    total = Float(default=0.0)
```

```python
# Good: rich — has behavior and rules
@domain.aggregate
class Order:
    customer_id = String(required=True)
    status = String(default="DRAFT")
    total = ValueObject(Money)

    def place(self, items):
        # Business logic lives here
        ...

    @invariant.post
    def total_must_not_exceed_limit(self):
        ...
```

## Tier 2: Common in Growing Codebases

These appear when the codebase grows beyond the initial design.

### Transaction Boundary Violation

Modifying multiple aggregates in one handler:

```python
# fragment
# Bad: two aggregates in one transaction
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    current_domain.repository_for(Order).add(order)
    # Violates: one aggregate per transaction
    inventory = current_domain.repository_for(Inventory).get(command.product_id)
    inventory.reduce(command.quantity)
    current_domain.repository_for(Inventory).add(inventory)
```

The fix keeps each handler to one aggregate. Order's own event handler reacts to `OrderPlaced` and sends a command, and Inventory's command handler changes Inventory. Events are delivered at least once, so the command carries the order id and Inventory's handler returns without changes for an order it has already reserved stock for:

```python
@domain.aggregate
class Inventory:
    available = Integer(default=0)
    reserved = Integer(default=0)
    reserved_order_ids = List(content_type=String)

    def reserve(self, order_id, quantity):
        self.available -= quantity
        self.reserved += quantity
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(required=True)


@domain.command(part_of="Inventory")
class ReserveStock:
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(required=True)


# Good: events for cross-aggregate coordination
@domain.command_handler(part_of="Order")
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        order = Order.create(...)  # Raises OrderPlaced event
        current_domain.repository_for(Order).add(order)
        return order.id


# Order's event handler reacts and hands off with a command
@domain.event_handler(part_of="Order")
class OrderEventHandler:
    @handle(OrderPlaced)
    def reserve_inventory(self, event):
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


@domain.command_handler(part_of="Inventory")
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.reserved_order_ids:
            return  # already reserved for this order
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)
```

### God Aggregate

One aggregate doing everything. `check` reports `AGGREGATE_TOO_LARGE` when the aggregate's cluster holds more child entities than `[lint] aggregate_size_limit` (default 5). Field and method counts are a judgement call that `check` does not make:

```python
# fragment
# Bad: Order handles ordering, shipping, payment, and notifications
@domain.aggregate
class Order:
    # 20+ fields
    # 15+ methods
    # Mix of ordering, shipping, payment logic
```

```python
# Good: separate aggregates per bounded context
@domain.aggregate
class Order: ...      # Ordering only

@domain.aggregate
class Shipment: ...   # Fulfillment only

@domain.aggregate
class Payment: ...    # Payments only
```

### Missing Events

Direct function calls instead of event-driven communication:

```python
# fragment
# Bad: direct call
def complete_order(order_id):
    order = repo.get(order_id)
    order.complete()
    repo.add(order)
    send_email(order.customer_email)  # Tight coupling
    update_analytics(order)            # More coupling
```

```python
@domain.command(part_of="Order")
class CompleteOrder:
    order_id = Identifier(required=True)


@domain.event(part_of="Order")
class OrderCompleted:
    order_id = Identifier(required=True)


# Good: event-driven
@domain.command_handler(part_of="Order")
class CompleteOrderHandler:
    @handle(CompleteOrder)
    def complete_order(self, command):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.complete()  # Raises OrderCompleted event
        repo.add(order)


# Separate handlers react
@domain.event_handler(part_of="Order")
class OrderConfirmations:
    @handle(OrderCompleted)
    def send_confirmation(self, event): ...


@domain.event_handler(part_of="Order")
class OrderAnalytics:
    @handle(OrderCompleted)
    def update_analytics(self, event): ...
```

## Tier 3: Subtle Issues

These are harder to spot but indicate architectural drift.

### Validation Duplication

Same rule checked in multiple places:

```python
# fragment
# Bad: validated in endpoint AND handler AND aggregate
@app.post("/orders")
def create_order(request):
    if request.quantity <= 0:  # Validation #1
        return {"error": "bad quantity"}
    ...

@handle(PlaceOrder)
def place_order(self, command):
    if command.quantity <= 0:  # Validation #2 (duplicate)
        raise ValueError(...)
    ...

@invariant.post
def quantity_must_be_positive(self):  # Validation #3 (duplicate)
    if self.quantity <= 0:
        raise ValidationError({"quantity": ["Quantity must be positive"]})
```

```python
# Good: validate once, at the right layer
@domain.aggregate
class OrderLine:
    # Field constraint handles basic validation
    quantity = Integer(required=True, min_value=1)

    # Invariant handles complex business rules
    @invariant.post
    def total_within_limit(self): ...
```

### Mock-Heavy Tests

Tests that mock domain internals instead of using real objects:

```python
# fragment
# Bad: mocking everything
def test_place_order():
    mock_repo = Mock()
    mock_repo.get.return_value = Order(status="DRAFT")
    handler = OrderHandler()
    handler.repository = mock_repo
    handler.place_order(PlaceOrder(...))
    mock_repo.add.assert_called_once()
```

```python
# Good: real objects with in-memory adapters. The test conftest sets
# command_processing to "sync", so process() returns the handler's result.
def test_place_order():
    order_id = domain.process(PlaceOrder(customer_id="c-1", items=[{"sku": "A1"}]))
    order = domain.repository_for(Order).get(order_id)
    assert order.status == "PLACED"
```

## Related

- [detection-heuristics.md](detection-heuristics.md) — How to find these programmatically
- [report-template.md](report-template.md) — How to present findings
