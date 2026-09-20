# Anti-Corruption Layer Pattern

The Anti-Corruption Layer (ACL) is a DDD pattern that prevents external system formats from leaking into your domain model. In Protean, subscribers serve as the ACL boundary.

## The problem

External systems use their own data formats, naming conventions, and schemas:
- ERP systems with camelCase and nested objects
- Payment gateways with status codes
- REST webhooks with envelope patterns

Without an ACL, external formats leak into your domain: `order.paymentGatewayStatus`, `customer.erpUserId`.

## The solution

The subscriber is the **single point of translation**. It knows the external format and translates it into domain-native language.

```
External System  →  [Broker Stream]  →  Subscriber (ACL)  →  Domain
                                         ↑
                                    Translation happens here
                                    Only class that imports nothing from external
```

## Translation strategies

### Field renaming

```python
# External: {"emailAddr": "alice@test.com"}
# Domain:   email="alice@test.com"
email = data["emailAddr"]
```

### Field combination

```python
# External: {"firstName": "Alice", "lastName": "Johnson"}
# Domain:   full_name="Alice Johnson"
full_name = f"{data['firstName']} {data['lastName']}"
```

### Status mapping

```python
# External: {"status": "COMPLETED"}
# Domain:   order.confirm_payment()
STATUS_MAP = {"COMPLETED": "confirm", "FAILED": "fail"}
```

### Nested unwrapping

```python
# External: {"data": {"user": {"id": "123"}}}
# Domain:   user_id="123"
user_id = data["data"]["user"]["id"]
```

## When to use each pattern

| Pattern | Use when |
|---------|---------|
| **Command dispatch** | Complex domain logic, multiple steps, need handler guards |
| **Direct update** | Simple status change, one aggregate, no guards needed |

## Key principles

1. **Only the subscriber knows the external format** — never expose external field names to domain code
2. **Domain stays clean** — commands and aggregates use domain language
3. **Single responsibility** — one subscriber per external system/stream
4. **Testable** — test the subscriber translation separately from domain logic
