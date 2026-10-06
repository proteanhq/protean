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

Similar to an aggregate, an entity's behavior can be customized by passing
options to its decorator. Protean does not read an inner `class Meta:` on an
entity, so options placed there are ignored.

Available options are:

### `auto_add_id_field`

If `True` (the default), Protean automatically adds an identifier field
(acting as primary key) to the entity. Set to `False` to suppress automatic
identity generation, useful when the entity defines its own explicit identifier
field.

### `schema_name`

The name to store and retrieve the entity from the persistence store. By
default, `schema_name` is the snake case version of the Entity's name.

### `database_model`

Similar to an aggregate, Protean automatically constructs a representation
of the entity that is compatible with the configured database. The generated
model suits most use cases. To control the mapping yourself, register your own
model with `@domain.database_model(part_of=<Entity>)`, as described in
[Database Models](../change-state/database-models.md). Passing a model through
this decorator option has no effect.

### `provider`

Inherited from the parent aggregate. Entities are always persisted in the same
persistence store as their aggregate. You cannot configure a separate provider
for an entity.

### `limit`

The maximum number of entity instances returned by default queries
(default: `100`). Set to `None` or a negative value to remove the limit.

!!!note
    An Entity is always persisted in the same persistence store as
    its Aggregate.

### `indexes`

Declares indexes for the entity's own table, using the same
[`Index`](../../reference/domain-elements/indexes.md) declarations as
aggregates:

```python
from protean import Index


@domain.aggregate
class Order:
    number: String(max_length=20)
    line_items = HasMany("LineItem")


@domain.entity(part_of=Order, indexes=[Index("sku", unique=True)])
class LineItem:
    sku = String(max_length=64)
    quantity = Integer()
```

See [Declaring Indexes](indexes.md) for the full workflow.

## Sharing Fields Through a Base Class

`@domain.entity` has no `abstract` option. Passing it raises
`ConfigurationError`. To share fields and behavior between entities, put them
on a subclass of `BaseEntity` and leave that class undecorated. Decorate only
the concrete subclasses:

```python
from protean.core.entity import BaseEntity
from protean.utils.reflection import declared_fields


class BaseLineItem(BaseEntity):
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


@domain.entity(part_of=Order)
class ProductLineItem(BaseLineItem):
    sku: String(max_length=64, required=True)


print(list(declared_fields(ProductLineItem)))
# ['quantity', 'unit_price', 'id', 'sku', 'order']
```

The base class is not registered with the domain and gets no table of its own.
It must subclass `BaseEntity`: a plain mixin class contributes no fields.

## Entity Lifecycle

Protean tracks the lifecycle state of every entity instance internally. The
state determines what happens when the aggregate is persisted:

| State | Property | Meaning |
|---|---|---|
| **New** | `_state.is_new` | Freshly constructed, not yet persisted. Inserted when the aggregate is next persisted with `repository.add()`. |
| **Persisted** | `_state.is_persisted` | Loaded from or saved to the database. No pending changes. |
| **Changed** | `_state.is_changed` | Modified since last persistence. Updated when the aggregate is next persisted with `repository.add()`. |
| **Destroyed** | `_state.is_destroyed` | Marked for deletion. Deleted when the aggregate is next persisted with `repository.add()`. |

State transitions happen automatically. You don't need to manage them directly.
Creating an entity marks it as *new*; modifying an attribute marks it as
*changed*; removing it from a collection marks it as *destroyed*; persisting
the aggregate marks surviving entities as *persisted*.

## Raising Events from Entities

Entities can raise domain events using the `raise_()` method, just like
aggregates. However, the event is always registered on the **aggregate root**,
not on the entity itself. The root is the owner of the event stream.

```python
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


@domain.event(part_of=Order)
class OrderItemQuantityChanged:
    order_id: Identifier(required=True)
    product_name: String(max_length=100)
    new_quantity: Integer()


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

Entities support the same invariant mechanism as aggregates, use `@invariant.post` to enforce
rules that must always hold:

```python
from protean.exceptions import ValidationError


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
alongside aggregate-level invariants. Both must pass for the aggregate cluster
to be in a valid state. See the [Invariants](../domain-behavior/invariants.md)
guide for details.

## The `defaults()` Hook

Override the `defaults()` method to set computed defaults that depend on
other field values:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer(default=1)
    unit_price: Decimal(precision=19, scale=4)
    line_total: Decimal(precision=19, scale=4)

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

You never persist an entity directly, always persist through the aggregate's
repository:

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(number="ORD-1", items=[OrderItem(product_name="Widget", quantity=2)])

    repo = domain.repository_for(Order)
    repo.add(order)  # Persists the order AND all its OrderItems
```

## Constructing from Value Objects

When commands and events carry entity data as value objects (see
[Projecting Entities into Value Objects](./value-objects.md#projecting-entities-into-value-objects)),
use the `from_value_object()` classmethod to convert them back:

```python
from protean import handle
from protean.fields import List, ValueObjectFromEntity


@domain.command(part_of=Order)
class PlaceOrder:
    number: String(max_length=20)
    items: List(content_type=ValueObjectFromEntity(OrderItem))


@domain.command_handler(part_of=Order)
class PlaceOrderHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        items = [OrderItem.from_value_object(item) for item in command.items]
        order = Order(number=command.number, items=items)
        domain.repository_for(Order).add(order)
```

The conversion itself needs no handler. With `OrderItem` as defined above:

```python
from protean import value_object_from_entity

OrderItemData = value_object_from_entity(OrderItem)

with domain.domain_context():
    data = OrderItemData(product_name="Widget", quantity=2)
    item = OrderItem.from_value_object(data)
    print(item.product_name, item.quantity)  # Widget 2
```

`from_value_object()` calls `vo.to_dict()` and constructs an entity instance.
Identity fields with `None` values are stripped so that auto-generated defaults
kick in. This means each converted entity gets a fresh identity rather than
failing validation.

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
    # Automatically gets: order_id, a shadow field holding the order's id
```

### Explicit Reference Fields

You can also define the reference field yourself, for example to rename its
shadow field. Tell the aggregate's `HasMany` about the new name with `via`:

```python
@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem", via="parent_order_id")

@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    order = Reference(Order, referenced_as="parent_order_id")
    # Creates shadow field 'parent_order_id' instead of 'order_id'
```

A `Reference` field may point only to the entity's parent: the aggregate root,
or the parent entity when the entity is nested. To link to a different
aggregate, store its identity in an `Identifier` field.

### Navigation Between Entities

Reference fields enable navigation from child entities back to their parent aggregate:

```python
with domain.domain_context():
    # Access parent aggregate from entity
    order_item = order.items[0]
    parent_order = order_item.order  # Order object
    order_id = order_item.order_id   # Order's ID value
```

For comprehensive relationship documentation, see [Expressing Relationships](./relationships.md) and [Association Fields](../../reference/fields/association-fields.md).

## Common Errors

| Exception | When it occurs |
|---|---|
| `IncorrectUsageError` | Entity defined without `part_of`; every entity must be associated with an aggregate. |
| `ValidationError` | Field validation fails during construction (e.g. missing `required` field). Contains a `messages` dict. |
| `ValidationError` | An `@invariant.post` check on the entity raises a validation error. |
| `ConfigurationError` | An unknown option is passed to `@domain.entity`, such as `abstract`. |
| `ConfigurationError` | Entity raises an event not associated with its aggregate root (`part_of` mismatch). |

---

!!! tip "See also"
    **Concept overview:** [Entities](../../concepts/building-blocks/entities.md): What entities are and how they relate to aggregates.

    **Decision guidance:** [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md): When to use an entity vs. an aggregate vs. a value object.

    **Related guides:**

    - [Invariants](../domain-behavior/invariants.md): Enforcing business rules on entities and aggregates.
    - [Raising Events](../domain-behavior/raising-events.md): How entities raise events through their aggregate root.
    - [Expressing Relationships](./relationships.md): Full relationship and association documentation.

    **Patterns:**

    - [Design Small Aggregates](../../patterns/design-small-aggregates.md): Drawing the right boundaries between aggregates and entities.
    - [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md): Named methods for controlled mutation.
