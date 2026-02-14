# Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Fields define the structure and behavior of data within domain elements —
Aggregates, Entities, Value Objects, Commands, and Events. They encapsulate
data properties, enforce validation, manage defaults, and express
relationships between domain concepts.

Protean provides a set of field functions (`String`, `Integer`, `Float`,
`HasMany`, etc.) that let you declare fields using domain-friendly vocabulary.
Under the hood, Protean uses Pydantic v2 as its validation and serialization
engine, so domain elements benefit from Rust-core validation performance,
JSON Schema generation, and native serialization — without requiring you to
learn Pydantic's API.

## Defining fields

Protean supports three styles for declaring fields: annotation style
(recommended), assignment style, and raw Pydantic style. All three are
fully supported and can be mixed within a single class.

```python
@domain.aggregate
class Product:
    name: String(max_length=50, required=True)   # annotation (recommended)
    price = Float(min_value=0)                    # assignment
```

Read more in [Defining fields](./defining-fields.md).

## Field arguments

Protean fields come with various options to model real-world scenarios effectively.
These include `required`, `default`, `choices`, and `unique`, among others, which allow for a highly customizable and robust
domain model definition.

Read more in [Arguments](./arguments.md) section.

## Types of fields

### Simple fields

[Simple fields](./simple-fields.md) handle basic data types like strings, integers, and dates.
They are the building blocks for defining straightforward data attributes in
models. Options like `max_length` for `String` or `max_value` and `min_value` for
numeric fields like `Integer` and `Float` allow you to specify constraints
directly in the model's definition.

### Container fields

[Container fields](./container-fields.md) are used for data types that hold multiple values, such as
lists and dictionaries. These fields support complex structures and provide
options such as `content_type` for `List` fields to ensure type consistency
within the collection. Protean optimizes storage and retrieval operations for
these fields by leveraging database-specific features when available.

### Association fields

[Association fields](./association-fields.md) define relationships between different domain models,
such as one-to-one, one-to-many, and many-to-many associations. These fields
help in mapping complex domain relationships and include functionalities to
manage related objects efficiently, preserving data integrity across the domain.
