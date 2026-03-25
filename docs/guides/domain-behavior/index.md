# Add Rules and Behavior

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Protean provides several mechanisms to define validation rules, enforce
business invariants, mutate aggregate state safely, and communicate state
changes through domain events. This section covers each of these
capabilities.

For the conceptual foundation, see
[Building Blocks](../../concepts/building-blocks/index.md).

## What's in This Section

### Validations

Validations ensure that data meets basic requirements before it can be processed. In Protean, validations can be applied at multiple levels:

- **Field-level restrictions** - Define type constraints, required fields, uniqueness
- **Built-in validators** - Leverage pre-defined validators for common validation patterns
- **Custom validators** - Create domain-specific validation logic

[Learn more about validations →](validations.md)

### Invariants

Invariants are business rules that must always hold true within your domain model. They preserve the consistency and integrity of your domain objects:

- **Always valid** - Invariants are conditions that must hold true at all times
- **Domain-driven** - Invariants stem from business rules and policies
- **Immediate validation** - Triggered automatically during initialization and state changes

[Learn more about invariants →](invariants.md)

### Status Transitions

Most aggregates are state machines. The `Status` field makes lifecycle rules explicit and automatically enforced:

- **Declarative transitions** - Define allowed state-to-state moves in the field declaration
- **Automatic enforcement** - Illegal transitions raise `ValidationError`
- **Terminal states** - States with no outgoing transitions are implicit
- **Programmatic checking** - `can_transition_to()` checks without raising

[Learn more about status transitions →](status-transitions.md)

### Aggregate Mutation

Aggregates encapsulate the state and behavior of your domain. Mutating their state is how you implement business operations:

- **State change methods** - Well-defined methods for modifying aggregate state
- **Invariant enforcement** - All state changes are validated against defined invariants
- **Explicit behavior** - Business operations are expressed as meaningful methods

[Learn more about aggregate mutation →](aggregate-mutation.md)

### Raising Events

Domain events record significant state changes and enable communication between different parts of your system:

- **Delta events** - Generated when aggregates mutate to record state changes
- **Entity events** - Any entity in an aggregate cluster can raise events
- **Event dispatching** - Events are automatically dispatched or can be manually published

[Learn more about raising events →](raising-events.md)

### Message Tracing & Enrichment

Protean automatically tracks causal chains across commands and events, and
lets you attach custom metadata to every message:

- **Correlation & causation IDs** - Automatically propagated through command → event chains
- **Causation chain API** - Walk up to the root command, down to all effects, or build a full causation tree programmatically
- **Message enrichment hooks** - Register callables that add custom metadata (user context, tenant ID, audit data) to every event and command
- **Extensions metadata** - A user-space `metadata.extensions` dict persisted in the event store

[Learn more about message tracing →](message-tracing.md) &nbsp;|&nbsp; [Learn more about message enrichment →](message-enrichment.md)

### Domain Services

Domain services encapsulate business logic that doesn't naturally fit within any single aggregate:

- **Stateless operations** - Pure functions that operate on multiple aggregates
- **Complex workflows** - Coordinate operations that span multiple aggregates
- **Business rules** - Enforce constraints that involve multiple objects

[Learn more about domain services →](domain-services.md)

### Error Handling

Raise, propagate, and handle domain exceptions -- from aggregate
invariants through command handlers to HTTP responses.

[Learn more about error handling →](error-handling.md)

!!! tip "See also"
    For design guidance and trade-offs, see the
    [Patterns & Recipes](../../patterns/index.md) section -- particularly
    [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md),
    [Validation Layering](../../patterns/validation-layering.md), and
    [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md).
