---
hide:
  - navigation
---

<!-- Show TOC on the left -->
<style>
    .md-sidebar--secondary {
        order: 0;
    }
</style>

# Glossary

### Aggregate
A cluster of domain objects that can be treated as a single unit. An aggregate always has one root entity.

### Application Service
A service that contains business logic and orchestrates operations across multiple aggregates or domains.

### Bounded Context
A boundary within which a particular domain model is defined and applicable. It ensures clear separation and encapsulation of models.

### Category
A logical grouping of related streams. It can represent a business domain or a part of it.

### Command
An instruction to perform a specific action, often resulting in a change of state within the system.

### Command Handler
A component responsible for processing commands and invoking corresponding actions on aggregates or domain services.

### Command Stream
A sequence of commands associated with a specific context or aggregate, recorded for tracking and processing purposes.

### Composition
The act of assembling smaller components into a more complex structure, often used to construct aggregates or services.

### CQRS
Command Query Responsibility Segregation, a design pattern that separates read and write operations to optimize performance and scalability.

### Custom Repository
A specialized repository that provides custom methods for accessing and manipulating aggregates or entities beyond the standard CRUD operations.

### DAO
Data Access Object, a pattern that provides an abstract interface to some type of database or other persistence mechanism.

### Domain
The sphere of knowledge and activity around which the business logic of the application revolves.

### Domain Service
A service that contains domain logic not belonging to any specific entity or value object, often operating across multiple aggregates.

### Entity
An object that is defined primarily by its identity rather than its attributes.

### Event
A significant change in state that is captured and recorded, typically representing a historical fact within the system.

### Event Handler
A component responsible for reacting to events, often used to trigger subsequent actions or processes.

### Event Sourcing
A pattern in which state changes are logged as a sequence of immutable events, enabling reconstruction of past states by replaying these events.

### Event Store Pattern
A storage pattern designed to persist events and support event sourcing, providing mechanisms to append and retrieve events efficiently.

### Event Stream
A chronological sequence of events related to a specific aggregate or bounded context, used to replay and reconstruct state.

### Identity
A unique identifier for an entity or aggregate, ensuring its distinctness within the system.

### Message
A piece of data sent between components, often used for communication and triggering actions in event-driven architectures.

### Projection
A read-only view of data that is constructed by processing one or more event streams, used to support query operations.

### Repository
A mechanism for encapsulating storage, retrieval, and search behavior for aggregates or entities, typically abstracting the underlying data store.

### Stream
A continuous flow of data or events, often used to represent a series of related messages or state changes within the system.

### Value Object
An immutable object that represents a descriptive aspect of the domain with no conceptual identity, defined only by its attributes.
