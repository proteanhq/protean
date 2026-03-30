# Entities

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Aggregates cluster multiple domain elements together to represent a concept.
They are usually composed of two kinds of elements - those with unique
identities (**Entities**) and those without (**Value Objects**).

Entities represent unique objects in the domain model just like Aggregates, but
they don't manage other objects. Just like Aggregates, Entities are identified
by unique identities that remain the same throughout its life - they are not
defined by their attributes or values. For example, a passenger in the airline
domain is an Entity. The passenger's identity remains the same across multiple
seat bookings, even if her profile information (name, address, etc.) changes
over time.

!!!note
    In Protean, Aggregates are actually entities that have taken on the
    additional responsibility of managing the lifecycle of one or more
    related entities.

## Definition

An Entity is defined with the `Domain.entity` decorator:

```python hl_lines="13-15"
--8<-- "guides/domain-definition/007.py:full"
```

An Entity has to be associated with an Aggregate. If `part_of` is not
specified while defining the identity, you will see an `IncorrectUsageError`:

```shell
>>> @publishing.entity
... class Comment:
...     content = String(max_length=500)
...
IncorrectUsageError: 'Entity `Comment` needs to be associated with an Aggregate'
```

An Entity cannot directly enclose an Aggregate. Trying to do so will
throw `IncorrectUsageError`.

However, entities *can* enclose other entities using `HasOne` and `HasMany`
relationships, as described in the [Associations](#associations) section below.

## Configuration

Similar to an aggregate, an entity's behavior can be customized with by passing
additional options to its decorator, or with a `Meta` class as we saw earlier.

Available options are:

### `abstract`

Marks an Entity as abstract if `True`. If abstract, the entity cannot be
instantiated and needs to be subclassed.

### `auto_add_id_field`

If `True` (the default), Protean automatically adds an identifier field
(acting as primary key) to the entity. Set to `False` to suppress automatic
identity generation — useful when the entity defines its own explicit
identifier field.

### `schema_name`

The name to store and retrieve the entity from the persistence store. By
default, `schema_name` is the snake case version of the Entity's name.

### `database_model`

Similar to an aggregate, Protean automatically constructs a representation
of the entity that is compatible with the configured database. While the
generated model suits most use cases, you can also explicitly construct a model
and associate it with the entity, just like in an aggregate.

### `provider`

Inherited from the parent aggregate. Entities are always persisted in the
same persistence store as their aggregate — you cannot configure a separate
provider for an entity.

### `limit`

The maximum number of entity instances returned by default queries
(default: `100`). Set to `None` or a negative value to remove the limit.

!!!note
    An Entity is always persisted in the same persistence store as
    its Aggregate.

## Entity Lifecycle

Protean tracks the lifecycle state of every entity instance internally. The
state determines what happens when the aggregate is persisted:

| State | Property | Meaning |
|---|---|---|
| **New** | `_state.is_new` | Freshly constructed, not yet persisted. Will be inserted on save. |
| **Persisted** | `_state.is_persisted` | Loaded from or saved to the database. No pending changes. |
| **Changed** | `_state.is_changed` | Modified since last persistence. Will be updated on save. |
| **Destroyed** | `_state.is_destroyed` | Marked for deletion. Will be removed on save. |

State transitions happen automatically — you don't need to manage them
directly. Creating an entity marks it as *new*; modifying an attribute marks
it as *changed*; removing it from a collection marks it as *destroyed*;
persisting the aggregate marks surviving entities as *persisted*.

## Raising Events from Entities

Entities can raise domain events using the `raise_()` method, just like
aggregates. However, the event is always registered on the **aggregate
root**, not on the entity itself — the root is the owner of the event
stream.

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()

    def update_quantity(self, new_qty):
        self.quantity = new_qty
        self.raise_(OrderItemQuantityChanged(
            order_id=str(self._owner.id),
            product_name=self.product_name,
            new_quantity=new_qty,
        ))
```

The event must be associated with the aggregate (`part_of=Order`), not
with the entity. Access the owning aggregate via `self._owner`.

## Invariants

Entities support the same invariant mechanism as aggregates — use
`@invariant.post` to enforce rules that must always hold:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()

    @invariant.post
    def quantity_must_be_positive(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError(
                {"quantity": ["Quantity must be positive"]}
            )
```

Entity invariants are checked whenever entity state changes. They work
alongside aggregate-level invariants — both must pass for the aggregate
cluster to be in a valid state. See the
[Invariants](../domain-behavior/invariants.md) guide for details.

## The `defaults()` Hook

Override the `defaults()` method to set computed defaults that depend on
other field values:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer(default=1)
    unit_price: Float()
    line_total: Float()

    def defaults(self):
        if self.line_total is None and self.unit_price is not None:
            self.line_total = self.quantity * self.unit_price
```

`defaults()` runs during initialization, after all field values have been
set but before invariants are checked. Aggregates, entities, and value
objects all support this hook.

## Persistence

Entities are always persisted as part of their parent aggregate's
transaction. In relational databases (SQLAlchemy provider), each entity
type gets its own table with a foreign key back to the aggregate. In
document databases (Elasticsearch provider), entities are typically stored
as nested documents within the aggregate's document.

You never persist an entity directly — always persist through the aggregate's
repository:

```python
repo = domain.repository_for(Order)
repo.add(order)  # Persists the order AND all its OrderItems
```

## Constructing from Value Objects

When commands and events carry entity data as value objects (see
[Projecting Entities into Value Objects](./value-objects.md#projecting-entities-into-value-objects)),
use the `from_value_object()` classmethod to convert them back:

```python
@domain.command_handler(part_of=Order)
class PlaceOrderHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        items = [OrderItem.from_value_object(item) for item in command.items]
        order = Order(customer_id=command.customer_id, items=items)
        # ...
```

`from_value_object()` calls `vo.to_dict()` and constructs an entity
instance. Identity fields with `None` values are stripped so that
auto-generated defaults kick in — this means each converted entity
gets a fresh identity rather than failing validation.

## Associations

Entities can enclose other entities within them using `HasOne` and `HasMany` relationships, similar to aggregates. Additionally, entities automatically receive `Reference` fields that establish inverse relationships to their parent aggregate.

### Automatic Reference Fields

When an entity is associated with an aggregate, Protean automatically creates a `Reference` field that points back to the parent:

```python
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")

@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    # Automatically gets: order = Reference(Order)
    # Automatically gets: order_id = String()  # Shadow field
```

### Explicit Reference Fields

You can also explicitly define reference fields for more control:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    order = Reference(Order, referenced_as="order_number")
    # Creates shadow field 'order_number' instead of 'order_id'
```

### Navigation Between Entities

Reference fields enable navigation from child entities back to their parent aggregate:

```python
# Access parent aggregate from entity
order_item = OrderItem(product_name="Widget", quantity=2)
parent_order = order_item.order  # Order object
order_id = order_item.order_id   # Order's ID value
```

For comprehensive relationship documentation, see [Expressing Relationships](./relationships.md) and [Association Fields](../../reference/fields/association-fields.md).

## Common Errors

| Exception | When it occurs |
|---|---|
| `IncorrectUsageError` | Entity defined without `part_of` — every entity must be associated with an aggregate. |
| `ValidationError` | Field validation fails during construction (e.g. missing `required` field). Contains a `messages` dict. |
| `ValidationError` | An `@invariant.post` check on the entity raises a validation error. |
| `IncorrectUsageError` | Trying to instantiate an abstract entity directly. |
| `ConfigurationError` | Entity raises an event not associated with its aggregate root (`part_of` mismatch). |

---

!!! tip "See also"
    **Concept overview:** [Entities](../../concepts/building-blocks/entities.md) — What entities are and how they relate to aggregates.

    **Decision guidance:** [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md) — When to use an entity vs. an aggregate vs. a value object.

    **Related guides:**

    - [Invariants](../domain-behavior/invariants.md) — Enforcing business rules on entities and aggregates.
    - [Raising Events](../domain-behavior/raising-events.md) — How entities raise events through their aggregate root.
    - [Expressing Relationships](./relationships.md) — Full relationship and association documentation.

    **Patterns:**

    - [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Drawing the right boundaries between aggregates and entities.
    - [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md) — Named methods for controlled mutation.
