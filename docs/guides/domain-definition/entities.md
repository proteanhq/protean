# Entities

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

Entities can be further enclose other entities within them, with the `HasOne`
and `HasMany` relationships, just like in an aggregate. Refer to the Aggregate's
[Association documentation](./aggregates.md#associations) for more details.
