# Defining a Domain (draft)

A [`Domain`](../../glossary.md#domain) in Protean represents a 
[Bounded Context](../../glossary.md#bounded-context) of the application. 
Because it is aware of all domain elements, a `Domain` in Protean acts as a 
Composition Root, with which all modules are composed together. It is 
responsible for creating and maintaining a graph of all the domain elements 
in the Bounded Context.

The Domain is the one-stop gateway to:

- Register domain elements
- Retrieve dynamically-constructed artifacts like repositories and models
- Access injected technology components at runtime

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

