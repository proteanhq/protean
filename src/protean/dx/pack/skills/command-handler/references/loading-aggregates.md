# Loading Aggregates (Hydration)

A "create" command builds a new aggregate from the command data. An "update" command loads the aggregate from the repository by its identifier first.

## Code

See [assets/command_handler_multiple_commands.py](../assets/command_handler_multiple_commands.py) for a handler that both creates and loads aggregates, and [assets/command_handler_create_aggregate.py](../assets/command_handler_create_aggregate.py) for the create pattern in detail.

The examples on this page use these elements:

```python
from protean import handle
from protean.fields import Identifier, String

@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    email: String(required=True)
    name: String()
    status: String(default="pending")

    def activate(self):
        self.status = "active"

@domain.command(part_of="Account")
class RegisterAccount:
    account_id: Identifier(required=True)
    email: String(required=True)
    name: String()

@domain.command(part_of="Account")
class ActivateAccount:
    account_id: Identifier(required=True)

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    shipping_address: String()

@domain.aggregate
class Shipment:
    shipment_id: Identifier(identifier=True)
    order_id: Identifier(required=True)
    address: String()

@domain.command(part_of="Shipment")
class FulfillOrder:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
```

## Creating a New Aggregate

```python
@domain.command_handler(part_of=Account)
class AccountRegistrationHandler:
    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        account = Account(
            account_id=command.account_id,
            email=command.email,
            name=command.name,
        )
        domain.repository_for(Account).add(account)
```

## Loading an Existing Aggregate

```python
@domain.command_handler(part_of=Account)
class AccountActivationHandler:
    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)
```

Both handlers belong to `Account`. One handler class with two `@handle` methods works the same way.

## Multiple Aggregates

A handler can load other aggregates to read them, and persists only one aggregate root (SKILL.md rule 7). Here the handler reads the `Order` and persists the `Shipment`:

```python
@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(FulfillOrder)
    def handle_fulfill(self, command: FulfillOrder):
        # Load the order (for reading)
        order = domain.repository_for(Order).get(command.order_id)

        # Create a shipment (the aggregate being persisted)
        shipment = Shipment(
            shipment_id=command.shipment_id,
            order_id=order.order_id,
            address=order.shipping_address,
        )
        domain.repository_for(Shipment).add(shipment)
        # Order changes should be synced via domain events
```

## Repository Access

Access the repository via `domain.repository_for(AggregateClass)`. Outside a handler, initialize the domain first and work inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    # Get a repository for the aggregate
    repo = domain.repository_for(Order)
    repo.add(Order(order_id="ORD-001", shipping_address="1 Main St"))

    # Load by identifier
    order = repo.get("ORD-001")

    # Persist (add or update)
    order.shipping_address = "2 Main St"
    repo.add(order)
```

The repository automatically handles both inserts (new aggregates) and updates (existing aggregates).

## Related

- [Unit of Work](./unit-of-work.md): Transactional behavior for persistence
- [Anti-patterns](./anti-patterns.md): Common mistakes when loading aggregates
- `aggregate`: Aggregate structure and behavior
