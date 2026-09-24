# Integration Test Patterns

Patterns for end-to-end flow testing and cross-aggregate event-driven coordination.

## Overview

Integration tests verify that the full pipeline works: command → handler → aggregate → event → event handler → state. They sit in the middle of the testing pyramid — write fewer of these than domain unit tests, but enough to cover critical paths.

## Code

Complete examples are in:
- [assets/scaffold_command_flow.py](../assets/scaffold_command_flow.py) — Command processing flow
- [assets/scaffold_event_driven_flow.py](../assets/scaffold_event_driven_flow.py) — Cross-aggregate event flow

## End-to-end command flow

Test the full journey from command to persisted state:

```python
class TestCommandFlow:
    def test_register_user_end_to_end(self):
        """Command → handler → aggregate → persisted."""
        result = domain.process(
            RegisterUser(email="a@test.com", name="Alice"),
            asynchronous=False,
        )
        user = domain.repository_for(User).get(result)
        assert user.status == "registered"
        assert user.email == "a@test.com"
```

## Cross-aggregate event flows

Test that events from one aggregate trigger correct state changes in another:

```python
class TestCrossAggregateFlow:
    def test_order_placed_reserves_inventory(self):
        """Order placement triggers inventory reservation."""
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        order = Order.place(customer_id="c-1", product_id="p-1", quantity=5)
        domain.repository_for(Order).add(order)

        updated_inv = domain.repository_for(Inventory).get(inventory.id)
        assert updated_inv.available == 95
        assert updated_inv.reserved == 5

    def test_multiple_orders_accumulate(self):
        """Multiple orders accumulate reservations."""
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        order1 = Order.place(customer_id="c-1", product_id="p-1", quantity=10)
        domain.repository_for(Order).add(order1)

        order2 = Order.place(customer_id="c-2", product_id="p-1", quantity=15)
        domain.repository_for(Order).add(order2)

        updated_inv = domain.repository_for(Inventory).get(inventory.id)
        assert updated_inv.available == 75
        assert updated_inv.reserved == 25
```

## Full lifecycle tests

Test multi-step sequences that exercise the complete domain:

```python
class TestLifecycle:
    def test_create_assign_audit_lifecycle(self):
        """Create ticket → assign → verify audit entry."""
        # Step 1: Create
        domain.process(
            CreateTicket(title="Bug", reporter="alice"),
            asynchronous=False,
        )
        tickets = domain.repository_for(Ticket)._dao.query.all()
        ticket = next(t for t in tickets.items if t.title == "Bug")

        # Step 2: Assign (triggers event handler → audit entry)
        domain.process(
            AssignTicket(ticket_id=ticket.id, assignee="bob"),
            asynchronous=False,
        )

        # Step 3: Verify final state
        updated = domain.repository_for(Ticket).get(ticket.id)
        assert updated.status == "assigned"
        assert updated.assignee == "bob"

        # Step 4: Verify side effects
        entries = domain.repository_for(AuditEntry)._dao.query.all()
        matching = [e for e in entries.items if e.ticket_id == ticket.id]
        assert len(matching) == 1
```

## When to use integration vs unit tests

| Scenario | Test type | Why |
|----------|-----------|-----|
| Aggregate method logic | Unit | Fast, focused, no infrastructure |
| Business rule enforcement | Unit | Test the rule in isolation |
| Command handler wiring | Integration | Verify handler→aggregate→persist pipeline |
| Event handler side effects | Integration | Verify cross-aggregate coordination |
| Full user workflow | Integration | Verify multi-step sequence |
| Value object operations | Unit | Test custom methods directly |

## Avoid mocks — use real domain elements

Integration tests should exercise the real domain pipeline. Use actual aggregates, commands, events, repositories, and event handlers — Protean's in-memory infrastructure and synchronous event processing make this straightforward. Mocks at the integration level defeat the purpose of testing the full flow. Only mock truly external dependencies (third-party HTTP APIs) that have no in-memory substitute.

## What NOT to test at the integration level

- Framework plumbing (registration, wiring, meta_ associations)
- Field-level validation (Protean Layer 1)
- Individual business rules that are better covered by unit tests

## Related

- [Aggregate test patterns](./aggregate-tests.md)
- [Handler test patterns](./handler-tests.md)
