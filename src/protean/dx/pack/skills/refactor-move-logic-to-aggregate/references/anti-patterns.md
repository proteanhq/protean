# Anti-Patterns in Logic Migration

The "Good" examples on this page run together. They use these events and this
command:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)


@domain.event(part_of="Ticket")
class TicketAssigned:
    ticket_id = Identifier(required=True)
    assignee_id = String(required=True)


@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
```

## Moving persistence into the aggregate

```python
# fragment
# Bad: aggregate knows about persistence
class Order:
    def place(self):
        self.status = "PLACED"
        domain.repository_for(Order).add(self)  # NO! Persistence stays in handler
```

```python
# Good: aggregate doesn't know about persistence
@domain.aggregate
class Order:
    customer_id = String(required=True)
    status = String(default="DRAFT")

    def place(self):
        self.status = "PLACED"
        self.raise_(OrderPlaced(order_id=self.id))
```

## Creating setter methods instead of business operations

```python
# fragment
# Bad: setters disguised as methods
class Ticket:
    def set_status(self, status):
        self.status = status

    def set_assignee(self, assignee_id):
        self.assignee_id = assignee_id
```

```python
# Good: business operations that capture intent
@domain.aggregate
class Ticket:
    status = String(default="OPEN")
    assignee_id = String()

    def assign(self, assignee_id):
        if self.status == "CLOSED":
            raise ValueError("Cannot assign closed ticket")
        self.assignee_id = assignee_id
        self.status = "ASSIGNED"
        self.raise_(TicketAssigned(ticket_id=self.id, assignee_id=assignee_id))
```

## Leaving events in the handler

```python
# fragment
# Bad: event raised in handler
@handle(PlaceOrder)
def place_order(self, command):
    order = Order(customer_id=command.customer_id)
    order.status = "PLACED"
    order.raise_(OrderPlaced(...))  # Should be inside order.place()
    domain.repository_for(Order).add(order)
```

```python
# Good: event raised inside aggregate method
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        order = Order(customer_id=command.customer_id)
        order.place()  # raise_() happens inside
        domain.repository_for(Order).add(order)
```

## Over-guarding with invariants

```python
# fragment
# Bad: invariant for something field constraints already handle
@invariant.post
def title_must_not_be_empty(self):
    if not self.title:
        raise ValidationError({"title": ["Title is required"]})
# Just use: title = String(required=True)
```

```python
# Good: invariant for cross-field business rules
from protean.exceptions import ValidationError


@domain.aggregate
class Task:
    title = String(required=True)
    status = String(default="OPEN")
    assignee_id = String()

    @invariant.post
    def assigned_must_have_assignee(self):
        if self.status == "ASSIGNED" and not self.assignee_id:
            raise ValidationError({"assignee_id": ["An assigned task needs an assignee"]})
```

## Related

- [identifying-logic-leaks.md](identifying-logic-leaks.md) — Detection heuristics
