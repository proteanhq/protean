# Anti-Patterns Catalog

Comprehensive catalog of anti-patterns found in Protean codebases, organized by how commonly they appear.

## Tier 1: Almost Universal

These appear in nearly every codebase that hasn't been through a design review.

### The "Controller Handler"

Handler does everything — validates, calculates, constructs, persists, and coordinates:

```python
# Bad: handler is a controller
@handle(PlaceOrder)
def place_order(self, command):
    if not command.items:
        raise ValidationError("Empty order")
    total = sum(i.price * i.qty for i in command.items)
    if total > MAX_ORDER:
        raise ValidationError("Too expensive")
    order = Order(customer_id=command.customer_id, total=total, status="PLACED")
    self.repository.add(order)

# Good: handler orchestrates, aggregate owns logic
@handle(PlaceOrder)
def place_order(self, command):
    order = Order(customer_id=command.customer_id)
    order.place(items=command.items)
    self.repository.add(order)
```

### Primitive Obsession

Using raw fields where value objects should model domain concepts:

```python
# Bad: raw fields
class Order:
    total_amount = Float()
    total_currency = String(default="USD")
    shipping_street = String()
    shipping_city = String()
    shipping_zip = String()

# Good: value objects
class Order:
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)
```

### The "Anemic Aggregate"

Aggregate is just a data container with no behavior:

```python
# Bad: anemic — no methods, no invariants
@domain.aggregate
class Order:
    customer_id = String(required=True)
    status = String(default="DRAFT")
    total = Float(default=0.0)

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
# Bad: two aggregates in one transaction
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    self.repository.add(order)
    # Violates: one aggregate per transaction
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reduce(command.quantity)
    domain.repository_for(Inventory).add(inventory)

# Good: events for cross-aggregate coordination
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)  # Raises OrderPlaced event
    self.repository.add(order)

# Separate handler reacts to the event
@handle(OrderPlaced)
def reserve_inventory(self, event):
    inventory = self.repository.get(event.product_id)
    inventory.reserve(event.quantity)
    self.repository.add(inventory)
```

### God Aggregate

One aggregate doing everything:

```python
# Bad: Order handles ordering, shipping, payment, and notifications
@domain.aggregate
class Order:
    # 20+ fields
    # 15+ methods
    # Mix of ordering, shipping, payment logic

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
# Bad: direct call
def complete_order(order_id):
    order = repo.get(order_id)
    order.complete()
    repo.add(order)
    send_email(order.customer_email)  # Tight coupling
    update_analytics(order)            # More coupling

# Good: event-driven
def complete_order(order_id):
    order = repo.get(order_id)
    order.complete()  # Raises OrderCompleted event
    repo.add(order)

# Separate handlers react
@handle(OrderCompleted)
def send_confirmation(self, event): ...

@handle(OrderCompleted)
def update_analytics(self, event): ...
```

## Tier 3: Subtle Issues

These are harder to spot but indicate architectural drift.

### Validation Duplication

Same rule checked in multiple places:

```python
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
        raise ValidationError(...)

# Good: validate once, at the right layer
# Field constraint handles basic validation
quantity = Integer(required=True, min_value=1)
# Invariant handles complex business rules
@invariant.post
def total_within_limit(self): ...
```

### Mock-Heavy Tests

Tests that mock domain internals instead of using real objects:

```python
# Bad: mocking everything
def test_place_order():
    mock_repo = Mock()
    mock_repo.get.return_value = Order(status="DRAFT")
    handler = OrderHandler()
    handler.repository = mock_repo
    handler.place_order(PlaceOrder(...))
    mock_repo.add.assert_called_once()

# Good: real objects with in-memory adapters
def test_place_order():
    domain.process(PlaceOrder(...), asynchronous=False)
    repo = domain.repository_for(Order)
    order = repo.get(order_id)
    assert order.status == "PLACED"
```

## Related

- [detection-heuristics.md](detection-heuristics.md) — How to find these programmatically
- [report-template.md](report-template.md) — How to present findings
