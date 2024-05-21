# Object Model

A domain model in Protean is composed with various types of domain elements,
all of which have a common structure and share a few behavioral traits. This
document outlines generic aspects that apply to every domain element.

## `Element` Base class

`Element` is a base class inherited by all domain elements. Currently, it does
not have any data structures or behavior associated with it.

## Element Type

<Element>.element_type

## Data Containers

Protean provides data container elements, aligned with DDD principles to model
a domain. These containers hold the data that represents the core concepts
of the domain.

There are three primary data container elements in Protean:

- Aggregates: The root element that represents a consistent and cohesive
collection of related entities and value objects. Aggregates manage their
own data consistency and lifecycle.
- Entities: Unique and identifiable objects within your domain that have
a distinct lifecycle and behavior. Entities can exist independently but
are often part of an Aggregate.
- Value Objects: Immutable objects that encapsulate a specific value or
concept. They have no identity and provide a way to group related data
without independent behavior.

### Reflection



## Metadata / Configuration Options

Additional options can be passed to a domain element in two ways:

- **`Meta` inner class**

You can specify options within a nested inner class called `Meta`:

```python hl_lines="13-14"
{! docs_src/guides/composing-a-domain/020.py !}
```

- **Decorator Parameters**

You can also pass options as parameters to the decorator:

```python hl_lines="7"
{! docs_src/guides/composing-a-domain/021.py !}
```
