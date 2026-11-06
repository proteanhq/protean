# Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Fields define the structure and behavior of data within domain elements,
Aggregates, Entities, Value Objects, Commands, and Events. Fields hold data
values, validate them, supply default values, and declare relationships between
domain concepts.

Protean provides a set of field functions (`String`, `Integer`, `Float`,
`Decimal`, `HasMany`, etc.) that let you declare fields using domain-friendly
vocabulary. Protean uses Pydantic v2 to validate and serialize domain elements,
which gives them Rust-core validation performance, JSON Schema generation, and
native serialization. You get these without learning Pydantic's API.

## Defining fields

Protean supports three styles for declaring fields: annotation style
(recommended), assignment style, and raw Pydantic style. All three are
fully supported and can be mixed within a single class.

```python
--8<-- "guides/domain-definition/fields/index-page/001.py:product"
```

Read more in [Defining fields](./defining-fields.md).

## Configure a field with arguments

Protean fields come with various options to model real-world scenarios effectively.
These include `required`, `default`, `choices`, and `unique`, among others,
which let you describe each field precisely in the domain model.

Read more in [Arguments](./arguments.md) section.

## Choose a type of field

### Simple fields

[Simple fields](./simple-fields.md) hold one value of a basic data type, such
as a string, an integer or a date. You use simple fields to define the
straightforward data attributes of a model. You can specify constraints
directly in the model's definition. For example, `max_length` limits a
`String`, and `max_value` and `min_value` limit numeric fields like `Integer`
and `Float`.

The `Status` field is a specialized simple field for modeling aggregate lifecycle
states with optional transition enforcement. See
[Status](./simple-fields.md#status) for details.

### Container fields

[Container fields](./container-fields.md) are used for data types that hold
multiple values, such as lists and dictionaries. Container fields support
complex structures. The `content_type` option on a `List` field checks that
every item in the collection has the same type. Protean optimizes storage and
retrieval operations for these fields by using database-specific features when
available.

### Association fields

[Association fields](./association-fields.md) define relationships between
different domain models, such as one-to-one, one-to-many, and many-to-many
associations. Association fields map complex domain relationships. They give
you methods that add, remove and look up related objects efficiently, which
preserves data integrity across the domain.
