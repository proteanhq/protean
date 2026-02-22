# Entities

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


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
{! docs_src/guides/domain-definition/007.py !}
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

An Entity cannot enclose another Entity (or Aggregate). Trying to do so will
throw `IncorrectUsageError`.

```shell
>>> @publishing.entity
... class SubComment:
...     parent = Comment()
... 
IncorrectUsageError: 'Entity `Comment` needs to be associated with an Aggregate'
```
<!-- FIXME Ensure entities cannot enclose other entities. When entities
enclose something other than permitted fields, through an error-->

## Configuration

Similar to an aggregate, an entity's behavior can be customized with by passing
additional options to its decorator, or with a `Meta` class as we saw earlier.

Available options are:

### `abstract`

Marks an Entity as abstract if `True`. If abstract, the entity cannot be
instantiated and needs to be subclassed.

### `auto_add_id_field`

If `True`, Protean will not add an identifier field (acting as primary key)
by default to the entity. This option is usually combined with `abstract` to
create entities that are meant to be subclassed by other aggregates.

### `schema_name`

The name to store and retrieve the entity from the persistence store. By
default, `schema_name` is the snake case version of the Entity's name.

### `database_model`

Similar to an aggregate, Protean automatically constructs a representation
of the entity that is compatible with the configured database. While the
generated model suits most use cases, you can also explicitly construct a model
and associate it with the entity, just like in an aggregate.

!!!note
    An Entity is always persisted in the same persistence store as the
    its Aggregate.

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

---

!!! tip "See also"
    **Concept overview:** [Entities](../../concepts/building-blocks/entities.md) — What entities are and how they relate to aggregates.

    **Patterns:**

    - [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Drawing the right boundaries between aggregates and entities.
