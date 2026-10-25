# Integration Test Patterns

Patterns for end-to-end flows and cross-aggregate coordination. An integration test runs the full pipeline: command → handler → aggregate → event → event handler → state. Write fewer of these than domain unit tests, but enough to cover the critical paths. SKILL.md Steps 4 and 5 show the basic command and side-effect tests. Complete examples:
- [assets/scaffold_command_flow.py](../assets/scaffold_command_flow.py): Command processing flow
- [assets/scaffold_event_driven_flow.py](../assets/scaffold_event_driven_flow.py): Cross-aggregate event flow

## Cross-aggregate event flows

Check that repeated events from one aggregate add up in another:

```python
class TestCrossAggregateFlow:
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
        domain.process(CreateTicket(title="Bug", reporter="alice"))
        tickets = domain.repository_for(Ticket).query.all()
        ticket = next(t for t in tickets.items if t.title == "Bug")

        # Step 2: Assign (triggers event handler → audit entry)
        domain.process(AssignTicket(ticket_id=ticket.id, assignee="bob"))

        # Step 3: Verify final state
        updated = domain.repository_for(Ticket).get(ticket.id)
        assert updated.status == "assigned"
        assert updated.assignee == "bob"

        # Step 4: Verify side effects
        entries = domain.repository_for(AuditEntry).query.all()
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

## Related

- [Aggregate test patterns](./aggregate-tests.md)
- [Handler test patterns](./handler-tests.md)
