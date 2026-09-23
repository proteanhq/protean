# Anti-Patterns in Logic Migration

## Moving persistence into the aggregate

```python
# Bad: aggregate knows about persistence
class Order:
    def place(self):
        self.status = "PLACED"
        domain.repository_for(Order).add(self)  # NO! Persistence stays in handler

# Good: aggregate doesn't know about persistence
class Order:
    def place(self):
        self.status = "PLACED"
        self.raise_(OrderPlaced(...))
```

## Creating setter methods instead of business operations

```python
# Bad: setters disguised as methods
class Ticket:
    def set_status(self, status):
        self.status = status

    def set_assignee(self, assignee_id):
        self.assignee_id = assignee_id

# Good: business operations that capture intent
class Ticket:
    def assign(self, assignee_id):
        if self.status == "CLOSED":
            raise ValueError("Cannot assign closed ticket")
        self.assignee_id = assignee_id
        self.status = "ASSIGNED"
        self.raise_(TicketAssigned(...))
```

## Leaving events in the handler

```python
# Bad: event raised in handler
@handle(PlaceOrder)
def place_order(self, command):
    order = Order(customer_id=command.customer_id)
    order.status = "PLACED"
    order.raise_(OrderPlaced(...))  # Should be inside order.place()
    domain.repository_for(Order).add(order)

# Good: event raised inside aggregate method
@handle(PlaceOrder)
def place_order(self, command):
    order = Order(customer_id=command.customer_id)
    order.place(items=command.items)  # raise_() happens inside
    domain.repository_for(Order).add(order)
```

## Over-guarding with invariants

```python
# Bad: invariant for something field constraints already handle
@invariant.post
def title_must_not_be_empty(self):
    if not self.title:
        raise ValidationError(...)
# Just use: title = String(required=True)

# Good: invariant for cross-field business rules
@invariant.post
def assigned_must_have_assignee(self):
    if self.status == "ASSIGNED" and not self.assignee_id:
        raise ValidationError(...)
```

## Related

- [identifying-logic-leaks.md](identifying-logic-leaks.md) — Detection heuristics
