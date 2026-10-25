# Handler Test Patterns

Patterns for testing command handler and event handler orchestration. Handler tests are integration tests: they check that a handler passes command or event data to the right aggregate method and persists the result. Complete examples:
- [assets/scaffold_command_flow.py](../assets/scaffold_command_flow.py): User registration with handler and API
- [assets/scaffold_event_driven_flow.py](../assets/scaffold_event_driven_flow.py): Cross-aggregate event handling

## Testing command handler orchestration

Use `domain.process(command)` to run the full handler pipeline. SKILL.md Step 4 shows the basic create-and-persist test. Two more checks:

```python
class TestHandlerProcessing:
    def test_handler_returns_identifier(self):
        """Handler returns aggregate ID."""
        result = domain.process(RegisterUser(email="b@test.com", name="Bob"))
        assert result is not None

    def test_multiple_commands_create_separate_aggregates(self):
        """Each command creates an independent aggregate."""
        r1 = domain.process(RegisterUser(email="a@test.com", name="A"))
        r2 = domain.process(RegisterUser(email="b@test.com", name="B"))
        assert r1 != r2
        u1 = domain.repository_for(User).get(r1)
        u2 = domain.repository_for(User).get(r2)
        assert u1.email == "a@test.com"
        assert u2.email == "b@test.com"
```

## Testing event handler side effects

SKILL.md Step 5 shows the basic side-effect test. In the Order and Inventory example, the event handler sits in Order's cluster (`part_of=Order`) and issues a `ReserveStock` command, and the command handler loads the Inventory. That is why the Inventory must be in the repository before the Order is persisted.

The command handler is where the write and its guard live. Events are delivered at least once, so test that a repeated command changes nothing:

```python
class TestReserveStockHandler:
    def test_a_repeated_command_reserves_once(self):
        inventory = Inventory(product_id="p-1", available=100)
        domain.repository_for(Inventory).add(inventory)

        command = ReserveStock(order_id="o-1", product_id="p-1", quantity=5)
        InventoryCommandHandler().reserve_stock(command)
        InventoryCommandHandler().reserve_stock(command)

        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 95
        assert updated.applied_order_ids == ["o-1"]
```

## Testing FastAPI endpoints

Use `TestClient` from FastAPI to test HTTP endpoints. It needs the `fastapi` and `httpx` packages:

```python
import pytest
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

## What NOT to test

Besides the skip list in SKILL.md, skip handler registration in `domain.registry.command_handlers` and the handler method count (`len(Handler._handlers)`). Both are framework internals.

## Related

- [Aggregate test patterns](./aggregate-tests.md)
- [Integration test patterns](./integration-tests.md)
