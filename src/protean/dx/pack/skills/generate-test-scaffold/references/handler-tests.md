# Handler Test Patterns

Patterns for testing command handler and event handler orchestration logic.

## Overview

Handler tests are integration tests — they verify that the handler wires command/event data to aggregate methods and persists results correctly. These sit in the middle of the testing pyramid.

## Code

Complete examples are in:
- [assets/scaffold_command_flow.py](../assets/scaffold_command_flow.py) — User registration with handler and API
- [assets/scaffold_event_driven_flow.py](../assets/scaffold_event_driven_flow.py) — Cross-aggregate event handling

## Testing command handler orchestration

Use `domain.process(command, asynchronous=False)` to test the full handler pipeline:

```python
class TestHandlerProcessing:
    def test_command_creates_and_persists_aggregate(self):
        """Handler creates aggregate and persists it."""
        result = domain.process(
            RegisterUser(email="a@test.com", name="Alice"),
            asynchronous=False,
        )
        user = domain.repository_for(User).get(result)
        assert user.email == "a@test.com"
        assert user.status == "registered"

    def test_handler_returns_identifier(self):
        """Handler returns aggregate ID."""
        result = domain.process(
            RegisterUser(email="b@test.com", name="Bob"),
            asynchronous=False,
        )
        assert result is not None

    def test_multiple_commands_create_separate_aggregates(self):
        """Each command creates an independent aggregate."""
        r1 = domain.process(
            RegisterUser(email="a@test.com", name="A"),
            asynchronous=False,
        )
        r2 = domain.process(
            RegisterUser(email="b@test.com", name="B"),
            asynchronous=False,
        )
        assert r1 != r2
        u1 = domain.repository_for(User).get(r1)
        u2 = domain.repository_for(User).get(r2)
        assert u1.email == "a@test.com"
        assert u2.email == "b@test.com"
```

## Testing event handler side effects

Event handlers fire when their source aggregate is persisted (with sync processing). Set up the target aggregate first:

```python
class TestEventHandlerSideEffects:
    def test_order_placed_reserves_inventory(self):
        """OrderPlaced triggers stock reservation in Inventory."""
        # Set up target aggregate first
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        # Source event fires when Order is persisted
        order = Order.place(customer_id="c-1", product_id="p-1", quantity=5)
        domain.repository_for(Order).add(order)

        # Verify side effect
        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 95
        assert updated.reserved == 5
```

**Key pattern**: The target aggregate (Inventory) must exist in the repository **before** the source aggregate (Order) is persisted, because the event handler needs to load it.

## Testing FastAPI endpoints

Use `TestClient` from Starlette/FastAPI to test HTTP endpoints:

```python
from fastapi.testclient import TestClient

class TestAPIEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_register_user_returns_201(self, client):
        response = client.post(
            "/users/register",
            json={"email": "a@test.com", "name": "Alice"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "registered"
        assert "user_id" in data

    def test_register_user_persists(self, client):
        """Verify the endpoint actually persists the aggregate."""
        response = client.post(
            "/users/register",
            json={"email": "b@test.com", "name": "Bob"},
        )
        user_id = response.json()["user_id"]
        user = domain.repository_for(User).get(user_id)
        assert user.name == "Bob"
```

## Avoid mocks — use real domain elements

Use `domain.process()` and `domain.repository_for()` with real commands, aggregates, and events. Protean's synchronous event processing (`domain.config["event_processing"] = "sync"`) and in-memory repositories eliminate the need for mocks. Do not mock handlers, repositories, or aggregate methods — test the real orchestration. Only mock truly external dependencies (third-party HTTP APIs) that have no in-memory substitute.

## What NOT to test

- Handler registration in `domain.registry.command_handlers` (framework guarantee)
- `meta_.part_of` association (framework wiring)
- `meta_.stream_category` (framework wiring)
- Handler method count (`len(Handler._handlers)`) (framework internals)
- Command field validation (Protean Layer 1)

## Related

- [Aggregate test patterns](./aggregate-tests.md)
- [Integration test patterns](./integration-tests.md)
