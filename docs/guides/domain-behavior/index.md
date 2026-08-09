# Add Rules and Behavior

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Once your domain elements exist, the next job is giving them rules: what
counts as valid data, which business conditions must always hold, how state is
allowed to change, and what the rest of the system hears about it afterwards.

For the conceptual foundation, see
[Building Blocks](../../concepts/building-blocks/index.md).

## Guides in this section

### Validations

Validations check that data meets basic requirements before it is processed.
You can constrain a field's type, mark it required, or make it unique. For
common patterns there are built-in validators, and for domain-specific rules
you can write your own.

[Learn more about validations →](validations.md)

### Invariants

An invariant is a business rule that must hold true at all times, and it is
what keeps your domain objects consistent. Invariants come from business rules
and policies rather than from the code, and Protean checks them automatically
during initialization and on every state change.

[Learn more about invariants →](invariants.md)

### Status Transitions

Most aggregates are state machines. The `Status` field lets you declare which
state-to-state moves are allowed, right in the field declaration, and Protean
raises `ValidationError` on any move you did not allow. A state with no
outgoing transitions is terminal, and `can_transition_to()` lets you check a
move without raising.

[Learn more about status transitions →](status-transitions.md)

### Aggregate Mutation

Aggregates hold the state and behaviour of your domain, and mutating that
state is how you implement a business operation. Write each operation as a
named method that says what it does, and Protean validates the result against
the aggregate's invariants.

[Learn more about aggregate mutation →](aggregate-mutation.md)

### Raising Events

Domain events record state changes worth telling the rest of the system about.
An aggregate raises a delta event when it mutates, any entity in the cluster
can raise one too, and Protean dispatches them for you or lets you publish
them by hand.

[Learn more about raising events →](raising-events.md)

### Message Tracing & Enrichment

Protean tracks causal chains across commands and events, propagating
correlation and causation IDs through each command-to-event chain. You can
walk up to the root command, down to all its effects, or build the full
causation tree in code. Enrichment hooks let you attach your own metadata,
such as user context, tenant ID, or audit data, to every message, and it is
persisted in a `metadata.extensions` dict in the event store.

[Learn more about message tracing →](message-tracing.md) &nbsp;|&nbsp; [Learn more about message enrichment →](message-enrichment.md)

### Domain Services

Some business logic does not belong to any single aggregate. A domain service
holds that logic: stateless operations across several aggregates, workflows
that span them, and rules that involve more than one object.

[Learn more about domain services →](domain-services.md)

### Error Handling

Raise, propagate, and handle domain exceptions, from aggregate invariants
through command handlers to HTTP responses.

[Learn more about error handling →](error-handling.md)

!!! tip "See also"
    For design guidance and trade-offs, see the
    [Patterns & Recipes](../../patterns/index.md) section, particularly
    [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md),
    [Validation Layering](../../patterns/validation-layering.md), and [Thin
    Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md).
