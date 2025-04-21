# Define Domain Concepts

Domain-driven Design (DDD) is all about identifying and naming domain concepts
and translating them as closely as possible - terminology, structure, and
behavior - in code. Protean supports the tactical patterns outlined by DDD
to mirror the domain model in [code model](../../glossary.md#code-model).

In this section, we will talk about the foundational structures that make up
the domain model. In the next, we will explore how to define behavior and
set up invariants (business rules) that bring the Domain model to life.

## Aggregates

One of the most important building block of a domain model is the Aggregate.
Aggregates are fundamental, coarse-grained building blocks of a domain model.
They are conceptual wholes - they enclose all behaviors and data of a distinct
domain concept. Aggregates are often composed of one or more Aggregate
Elements, that work together to codify the concept.

Aggregates act as **Root Entities** - they manage the lifecycle
of all [Entities](../../glossary.md#entity) and 
[Value Objects](../../glossary.md#value-object) enclosed within them.
Aggregates are just [entities](#entities), in that sense, but are responsible
for all other enclosed entities. Elements enclosed within an Aggregate are
only accessible through the Aggregate itself - it acts as a consistency
boundary and protects data sanctity within the cluster.

Read more about [Aggregates](../../core-concepts/domain-elements/aggregates.md) in the Core Concepts section.

## Entities

Entities are domain objects with unique identities that remain the same throughout their lifecycle, even if their attributes change. Unlike Value Objects, Entities are distinguished by their identity rather than their attributes.

Key characteristics of Entities include:

- **Identity**: Each Entity has a unique identifier that remains constant throughout its lifecycle
- **Mutability**: Entities can change their state over time while maintaining their identity
- **Part of an Aggregate**: Entities must be associated with an Aggregate and are accessed through it
- **Lifecycle Management**: Their lifecycle is managed by the Aggregate they belong to

See [Entities](./entities.md) for more information.

## Value Objects

Value Objects represent descriptive aspects of the domain with no conceptual identity. They are defined entirely by their attributes and are immutable - once created, they cannot be changed.

Value Objects are characterized by:

- **Identity through Attributes**: Two Value Objects with the same attributes are considered equal
- **Immutability**: They cannot be modified after creation; any change creates a new instance
- **Purpose**: They encapsulate related attributes and associated validation rules
- **Composition**: Value Objects can contain other Value Objects to represent complex attributes

Learn more in the [Value Objects](./value-objects.md) guide and [Value Objects Core Concepts](../../core-concepts/domain-elements/value-objects.md).

### Events

Events are immutable facts that indicate a state change in the domain. They capture what has happened in the system and allow different parts of the application to react accordingly.

Key characteristics of Events include:

- **Immutable Records**: Events represent facts that have occurred and cannot be changed
- **Association with Aggregates**: Events are always associated with the Aggregate that emits them
- **Past-tense Naming**: Events are named using past-tense verbs (e.g., `OrderPlaced`)
- **State Preservation**: Events help preserve domain state and history
- **Communication Medium**: They enable decoupled communication between different parts of the system
- **Structure**: Events contain metadata, timestamps, version information, and relevant data about the change

Events can be processed either synchronously or asynchronously, depending on your application's needs. See the [Events](./events.md) guide and [Events Core Concepts](../../core-concepts/domain-elements/events.md) for more details.
