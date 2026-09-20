# Testing Endpoints

How to test Protean FastAPI endpoints using FastAPI's TestClient.

## Overview

API endpoint tests verify the full HTTP-to-domain flow: request in, response out. They use FastAPI's `TestClient` which provides synchronous HTTP calls against the app without needing a running server.

## Code

Test examples for all asset files are in the parallel `tests/api-endpoint/` directory.

## Test Setup Pattern

```python
import pytest
from fastapi.testclient import TestClient
from api_endpoint_simple import app, domain

@pytest.fixture
def client():
    return TestClient(app)
```

The `conftest.py` at the tests root automatically:
1. Adds asset directories to `sys.path` for direct imports
2. Calls `domain.init(traverse=False)` and enters domain context via `auto_domain_context`

## What to Test

### 1. Successful Operations

Test the happy path -- valid request, expected status code, expected response body.

```python
def test_create_order(self, client):
    response = client.post("/orders", json={
        "order_id": "ORD-001",
        "customer_id": "CUST-123",
        "total_amount": 99.99,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == "ORD-001"
    assert data["status"] == "placed"
```

### 2. Missing Required Fields

Test that missing fields produce appropriate errors.

```python
def test_missing_field(self, client):
    response = client.post("/orders", json={
        "order_id": "ORD-001",
        # missing customer_id and total_amount
    })
    assert response.status_code != 201  # Error response
```

### 3. Path Parameters

Test that URL path parameters are correctly mapped to command fields.

```python
def test_cancel_with_path_param(self, client):
    # Create first, then cancel
    client.post("/orders", json={...})
    response = client.put("/orders/ORD-001/cancel", json={"reason": "Changed mind"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
```

### 4. Pydantic Validation

Test that Pydantic validation returns 422 for invalid input.

```python
def test_invalid_email(self, client):
    response = client.post("/accounts/register", json={
        "account_id": "ACC-001",
        "email": "not-an-email",
        "name": "Alice",
    })
    assert response.status_code == 422
```

### 5. Multi-Step Workflows

Test sequences of operations on the same aggregate.

```python
def test_full_lifecycle(self, client):
    # Create
    client.post("/shipments", json={...})
    # Update tracking
    client.put("/shipments/SHP-001/tracking", json={...})
    # Deliver
    response = client.put("/shipments/SHP-001/deliver")
    assert response.json()["status"] == "delivered"
```

## TestClient Details

- `TestClient` is synchronous even though endpoints are `async`
- Middleware (including domain context) runs normally
- JSON payloads via `json=` parameter (sets Content-Type automatically)
- Access response with `.status_code`, `.json()`, `.text`

## Related

- [Request Validation](./request-validation.md) - What to validate at the boundary
- [Response Patterns](./response-patterns.md) - Expected response shapes
- [command-handler skill](../../command-handler/SKILL.md) - Testing command handlers
