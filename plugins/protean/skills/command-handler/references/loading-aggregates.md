# Loading Aggregates (Hydration)

Command handlers are responsible for loading (hydrating) aggregates from the repository before invoking methods on them.

## Overview

There are two scenarios in a command handler:

1. **Creating a new aggregate** - Construct a new instance directly from command data
2. **Loading an existing aggregate** - Retrieve from the repository using an identifier

The choice depends on the nature of the command (e.g., "create" vs. "update").

## Code

See [assets/command_handler_multiple_commands.py](../assets/command_handler_multiple_commands.py) for a handler that demonstrates both creating and loading aggregates, and [assets/command_handler_create_aggregate.py](../assets/command_handler_create_aggregate.py) for the create pattern in detail.

Key highlights:
- Use `domain.repository_for(Aggregate).get(id)` to load an existing aggregate
- Construct new aggregate instances directly when creating
- Always persist via `domain.repository_for(Aggregate).add(aggregate)` after mutation

## Creating a New Aggregate

When handling a "create" command, construct the aggregate from command data:

```python
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

When handling an "update" command, load from the repository first:

```python
@handle(ActivateAccount)
def handle_activate(self, command: ActivateAccount):
    account = domain.repository_for(Account).get(command.account_id)
    account.activate()
    domain.repository_for(Account).add(account)
```

## Repository Access

Access the repository via `domain.repository_for(AggregateClass)`:

```python
# Get a repository for the aggregate
repo = domain.repository_for(Order)

# Load by identifier
order = repo.get("ORD-001")

# Persist (add or update)
repo.add(order)
```

The repository automatically handles both inserts (new aggregates) and updates (existing aggregates).

## Multiple Aggregates

A handler can load more than one aggregate if the business process requires it, but it should only persist ONE aggregate root. Cross-aggregate coordination should happen through domain events.

```python
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

## Related

- [Unit of Work](./unit-of-work.md) - Transactional behavior for persistence
- [Anti-patterns](./anti-patterns.md) - Common mistakes when loading aggregates
- `aggregate` - Aggregate structure and behavior
