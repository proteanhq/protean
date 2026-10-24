# Anti-Corruption Layer Pattern

The Anti-Corruption Layer (ACL) is a DDD pattern that prevents external system formats from leaking into your domain model. In Protean, subscribers serve as the ACL boundary.

## The problem

External systems use their own data formats, naming conventions, and schemas. Without an ACL, external formats leak into your domain: `order.paymentGatewayStatus`, `customer.erpUserId`.

## The solution

The subscriber is the **single point of translation**. It knows the external format and translates it into domain-native language.

```
External System  →  [Broker Stream]  →  Subscriber (ACL)  →  Domain
                                         ↑
                                    Translation happens here
                                    Only class that knows the external format
```

## Translation strategies

### Field renaming

```python
# fragment
# External: {"emailAddr": "alice@test.com"}
# Domain:   email="alice@test.com"
email = data["emailAddr"]
```

### Field combination

```python
# fragment
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
# fragment
# External: {"data": {"user": {"id": "123"}}}
# Domain:   user_id="123"
user_id = data["data"]["user"]["id"]
```

## One subscriber per external system

Give each external system or stream its own subscriber.
